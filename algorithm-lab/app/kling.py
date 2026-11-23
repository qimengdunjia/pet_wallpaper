"""文件用途：适配可灵两代任务结构，提交图片/视频、查询状态并下载真实成品。"""

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from PIL import Image

from .config import Settings
from .image import DEFAULT_IMAGE_OPTIONS, STANDARD_IMAGE_MODEL, ImageOptions
from .video import DEFAULT_VIDEO_OPTIONS, OMNI_VIDEO_MODEL, VideoOptions


def _image_endpoint(model: str | None) -> str:
    return "/v1/images/generations" if model == STANDARD_IMAGE_MODEL else "/v1/images/omni-image"


class ProviderError(Exception):
    """表示可向用户展示的供应商错误；参数 message 为原因，resumable 表示可继续原任务。"""

    def __init__(self, message: str, resumable: bool = False):
        super().__init__(message)
        self.resumable = resumable


class SubmissionUnknown(ProviderError):
    """表示付费提交结果不明；禁止自动重复提交，需通过控制台核对。"""


@dataclass
class RemoteTask:
    """统一远端任务结果；state 为状态，url 为临时成品地址，message 为简短原因。"""

    state: str
    url: str | None = None  # 临时远端链接仅保存于后端状态文件。
    message: str = ""


class KlingProvider:
    """实现真实云端适配；参数 settings 为配置，client 可注入 HTTP 测试客户端。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=90)

    async def close(self) -> None:
        """关闭 HTTP 连接池；无参数，无返回值。"""
        await self.client.aclose()

    def _message(self, value) -> str:
        message = str(value).replace(self.settings.api_key, "[已隐藏]") if self.settings.api_key else str(value)
        return re.sub(r"https?://\S+", "[远端链接]", message)[:240]

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = await self.client.request(
                method, self.settings.base_url + path,
                headers={"Authorization": f"Bearer {self.settings.api_key}"}, **kwargs,
            )
        except httpx.HTTPError as exc:
            if method == "POST":
                raise SubmissionUnknown("提交连接中断，无法确认是否已创建付费任务，请先到可灵控制台核对") from exc
            raise ProviderError("暂时无法查询可灵，请检查网络后继续查询原任务", True) from exc
        if response.status_code >= 500 or response.status_code == 408:
            if method == "POST":
                raise SubmissionUnknown("可灵提交响应异常，需核对控制台后再继续")
            raise ProviderError(f"可灵查询暂不可用（HTTP {response.status_code}）", True)
        if response.status_code >= 400:
            raise ProviderError(f"可灵拒绝请求（HTTP {response.status_code}），请检查密钥、区域、权限或额度", method == "GET")
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("响应不是对象")
        except ValueError as exc:
            if method == "POST":
                raise SubmissionUnknown("可灵返回无法解析的提交响应，请核对控制台") from exc
            raise ProviderError("可灵查询响应无法解析", True) from exc
        if "code" not in payload:
            if method == "POST":
                raise SubmissionUnknown("可灵提交响应缺少确认状态，请先核对控制台")
            raise ProviderError("可灵查询响应缺少确认状态", True)
        if str(payload.get("code")) != "0":
            raise ProviderError(f"可灵错误 {payload.get('code', '未知')}：{self._message(payload.get('message', '请求失败'))}", method == "GET")
        return payload

    async def submit(self, stage: str, references: list[Path], external_id: str,
                     *, video_options: VideoOptions | None = None, video_prompt: str | None = None,
                     image_prompt: str | None = None, image_options: ImageOptions | None = None) -> str:
        """提交一次生成；参数为阶段、素材、追踪 ID 和可选的生成设置与提示词，返回远端任务 ID。"""
        if stage == "idle":
            options = image_options or DEFAULT_IMAGE_OPTIONS
            payload = {
                "model_name": options.model,
                "prompt": image_prompt,
                "resolution": options.resolution, "aspect_ratio": options.aspect_ratio,
                "n": 1, "external_task_id": external_id,
            }
            if options.model == STANDARD_IMAGE_MODEL:
                if len(references) != 1:
                    raise ProviderError("普通 Image 3.0 每个任务需要一张参考图")
                payload["image"] = base64.b64encode(references[0].read_bytes()).decode("ascii")
            else:
                payload["image_list"] = [{"image": base64.b64encode(p.read_bytes()).decode("ascii")} for p in references]
                payload["result_type"] = "single"
            result = await self._request("POST", _image_endpoint(options.model), json=payload)
            data = result.get("data")
            task_id = data.get("task_id") if isinstance(data, dict) else None
        else:
            options = video_options or DEFAULT_VIDEO_OPTIONS
            # 帧数据来自已保存的本机副本，使用原始 Base64。
            encoded = [base64.b64encode(path.read_bytes()).decode("ascii") for path in references]
            if options.model == OMNI_VIDEO_MODEL:
                images = [{"image_url": encoded[0], "type": "first_frame"}]
                reference_start = 1
                if options.frame_mode == "first_last":
                    images.append({"image_url": encoded[1] if len(encoded) > 1 else encoded[0], "type": "end_frame"})
                    reference_start = 2
                images.extend({"image_url": image} for image in encoded[reference_start:])
                payload = {
                    "model_name": "kling-v3-omni", "prompt": video_prompt, "image_list": images,
                    "mode": {"720p": "std", "1080p": "pro", "4k": "4k"}[options.resolution],
                    "duration": str(options.duration), "external_task_id": external_id,
                }
                result = await self._request("POST", "/v1/videos/omni-video", json=payload)
                data = result.get("data")
                task_id = data.get("task_id") if isinstance(data, dict) else None
            else:
                first_frame = encoded[0]
                contents = [{"type": "prompt", "text": video_prompt}, {"type": "first_frame", "url": first_frame}]
                if options.frame_mode == "first_last":
                    contents.append({"type": "last_frame", "url": encoded[1] if len(encoded) > 1 else first_frame})
                if options.model == "kling-4.0":
                    for frame, frame_id in zip(contents[1:], ("start", "end")):
                        frame["id"] = frame_id
                settings = {"duration": options.duration, "resolution": options.resolution}
                if options.model == "kling-3.0":
                    settings.update(multi_shot=False)
                result = await self._request(
                    "POST", f"/image-to-video/{options.model}", json={"contents": contents, "settings": settings},
                )
                data = result.get("data")
                task_id = data.get("id") if isinstance(data, dict) else None
        if not task_id:
            raise SubmissionUnknown("可灵响应缺少任务 ID，请到控制台核对，禁止盲目再次生成")
        return str(task_id)

    async def query(self, stage: str, task_id: str, *, image_model: str | None = None,
                    video_model: str | None = None) -> RemoteTask:
        """查询已有任务；参数为阶段、远端 ID 和可选图片模型，返回统一状态。"""
        if stage == "video" and video_model == OMNI_VIDEO_MODEL:
            result = await self._request("GET", f"/v1/videos/omni-video/{quote(task_id, safe='')}")
            task = result.get("data")
            if not isinstance(task, dict):
                raise ProviderError("Omni 视频任务查询结构异常", True)
            state = task.get("task_status")
            videos = (task.get("task_result") or {}).get("videos") or []
            url = videos[0].get("url") if videos else None
            message = task.get("task_status_msg", "")
        elif stage == "video":
            result = await self._request("GET", "/tasks", params={"task_ids": task_id})
            data = result.get("data", [])
            if not isinstance(data, list):
                raise ProviderError("视频任务查询结构异常", True)
            task = next((x for x in data if str(x.get("id")) == task_id), None)
            if not task:
                raise ProviderError("当前区域未查询到该视频任务，请核对任务 ID", True)
            state = task.get("status")
            outputs = task.get("outputs") or []
            url = next((x.get("url") for x in outputs if x.get("type") == "video"), None)
            message = task.get("message", "")
        else:
            result = await self._request("GET", f"{_image_endpoint(image_model)}/{quote(task_id, safe='')}")
            task = result.get("data")
            if not isinstance(task, dict):
                raise ProviderError("图片任务查询结构异常", True)
            state = task.get("task_status")
            images = (task.get("task_result") or {}).get("images") or []
            url = images[0].get("url") if images else None
            message = task.get("task_status_msg", "")
        if state in {"succeed", "succeeded"}:
            if not url:
                raise ProviderError("任务已完成但成品链接尚不可用，请继续查询原任务", True)
            return RemoteTask("complete", str(url))
        if state == "failed":
            return RemoteTask("failed", message=self._message(message) or "供应商生成失败")
        if state not in {"submitted", "processing"}:
            raise ProviderError("可灵返回未知任务状态，请继续查询原任务", True)
        return RemoteTask("running")

    async def download(self, stage: str, url: str, target: Path) -> dict:
        """下载并校验成品；参数为阶段、远端 URL、无后缀路径，返回本地文件登记信息。"""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ProviderError("供应商返回的成品链接格式不正确", True)
        # 下载连接不携带可灵 Authorization，避免把密钥发给素材 CDN。
        limit = 100 * 1024 * 1024 if stage == "video" else 10 * 1024 * 1024
        temporary = target.with_suffix(".part")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as downloader:
                async with downloader.stream("GET", url) as response:
                    response.raise_for_status()
                    count = 0
                    with temporary.open("wb") as handle:
                        async for chunk in response.aiter_bytes():
                            count += len(chunk)
                            if count > limit:
                                raise ProviderError("成品文件超过本机限制，请检查供应商输出规格", True)
                            handle.write(chunk)
            if stage == "video":
                with temporary.open("rb") as handle:
                    header = handle.read(32)
                if header[4:8] != b"ftyp":
                    raise ProviderError("视频成品不是可识别的 MP4 文件", True)
                suffix, mime = ".mp4", "video/mp4"
            else:
                with Image.open(temporary) as image:
                    image.verify()
                    encoding = image.format
                if encoding not in {"JPEG", "PNG"}:
                    raise ProviderError("图片成品不是 JPEG 或 PNG", True)
                suffix, mime = (".png", "image/png") if encoding == "PNG" else (".jpg", "image/jpeg")
            destination = target.with_suffix(suffix)
            temporary.replace(destination)
            return {"file": destination.name, "mime": mime, "remote_url": url}
        except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise ProviderError("成品下载或校验失败；重试将查询原任务并重新下载，不会再次生成", True) from exc
        finally:
            temporary.unlink(missing_ok=True)
