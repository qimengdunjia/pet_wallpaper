"""文件用途：通过 ComfyUI API 生成待机图、待机视频和三个交互视频，并恢复远端任务。"""

from __future__ import annotations

import asyncio
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

from .comfyui_workflows import OUTPUT_NODE, image_workflow, video_workflow
from .config import Settings
from .generation_settings import default_generation_settings
from .providers import BaseGenerationProvider, PersistRemoteFn, ProgressFn, ProviderError

VIDEO_STAGES = (("idle-video", "idle", 40), ("left", "left", 55), ("center", "center", 70), ("right", "right", 85))


def _compress_reference(path: Path, max_bytes: int) -> BytesIO:
    """按传输上限压缩模型参考图，返回可直接上传的 JPEG。"""
    with Image.open(path) as source:
        source.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
        image = source if source.mode == "RGB" else source.convert("RGB")
        dimension = max(image.size)
        while dimension >= 256:
            encoded = BytesIO()
            image.thumbnail((dimension, dimension), Image.Resampling.LANCZOS)
            image.save(encoded, format="JPEG", quality=90, optimize=True)
            if encoded.tell() <= max_bytes:
                encoded.seek(0)
                return encoded
            dimension = dimension * 3 // 4
    raise ProviderError("参考图无法压缩到当前 ComfyUI 传输上限")


class ComfyUIGenerationProvider(BaseGenerationProvider):
    """将宠物照片交给 MiniMax H3，再将生成的待机图交给 Pika H3 生成四段视频。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=90, trust_env=False)

    async def close(self) -> None:
        """关闭 ComfyUI HTTP 连接池，无返回值。"""
        await self.client.aclose()

    async def _json(self, method: str, endpoint: str, **kwargs) -> dict:
        try:
            response = await self.client.request(method, endpoint, **kwargs)
            if response.status_code >= 400:
                temporary = response.status_code >= 500 and method == "GET"
                raise ProviderError(f"ComfyUI 接口返回 HTTP {response.status_code}，请检查服务和工作流节点", temporary)
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("响应不是对象")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError("无法连接或读取 ComfyUI，请检查服务和 SSH 转发", method == "GET") from exc

    async def _upload(self, base: str, path: Path, name: str) -> str:
        mime = "image/png" if path.suffix == ".png" else "image/jpeg"
        limit = self.settings.comfyui_reference_max_bytes
        if limit and path.stat().st_size > limit:
            file = await asyncio.to_thread(_compress_reference, path, limit)
            name = str(Path(name).with_suffix(".jpg"))
            mime = "image/jpeg"
        else:
            file = path.open("rb")
        with file:
            uploaded = await self._json(
                "POST", f"{base}/upload/image", files={"image": (name, file, mime)},
                data={"type": "input", "subfolder": "pet_wallpaper_demo", "overwrite": "true"},
            )
        returned_name = uploaded.get("name")
        subfolder = uploaded.get("subfolder") or ""
        if not isinstance(returned_name, str) or not returned_name:
            raise ProviderError("ComfyUI 上传图片响应缺少文件名")
        return f"{subfolder}/{returned_name}" if subfolder else returned_name

    async def _download(self, base: str, output: dict, target: Path) -> None:
        limit = 150 * 1024 * 1024 if target.suffix == ".mp4" else 25 * 1024 * 1024
        tmp = target.with_suffix(".part")
        try:
            async with self.client.stream("GET", f"{base}/view", params={
                "filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": "output",
            }) as response:
                response.raise_for_status()
                total = 0
                with tmp.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > limit:
                            raise ProviderError("ComfyUI 成品体积超出限制")
                        file.write(chunk)
                if not total:
                    raise ProviderError("ComfyUI 成品为空")
            tmp.replace(target)
        except httpx.HTTPError as exc:
            raise ProviderError("无法下载 ComfyUI 成品，请检查服务和 SSH 转发", True) from exc
        finally:
            tmp.unlink(missing_ok=True)

    async def _collect(self, base: str, task_id: str, target: Path) -> dict:
        """轮询任务历史、下载成品并返回 ComfyUI 成品记录。"""
        deadline = time.monotonic() + self.settings.comfyui_task_timeout
        errors = 0
        while time.monotonic() < deadline:
            try:
                history = await self._json("GET", f"{base}/history/{quote(task_id, safe='')}")
                task = history.get(task_id)
                if task:
                    status = task.get("status", {})
                    if status.get("status_str") == "error":
                        raise ProviderError(f"ComfyUI 工作流执行失败，请检查服务中的任务 {task_id}")
                    outputs = task.get("outputs", {}).get(OUTPUT_NODE, {})
                    # 原生 SaveVideo 的成片在部分版本的 images 字段中返回。
                    files = [item for key in ("videos", "images", "gifs") for item in outputs.get(key, [])]
                    for item in files:
                        if item.get("type") == "output" and str(item.get("filename", "")).lower().endswith(target.suffix):
                            await self._download(base, item, target)
                            return item
                    if status.get("completed"):
                        raise ProviderError("ComfyUI 已完成任务，但没有返回所需格式的成品")
                errors = 0
            except ProviderError as exc:
                errors += 1
                if not exc.resumable or errors >= 5:
                    raise
            await asyncio.sleep(self.settings.comfyui_poll_seconds)
        raise ProviderError(f"等待 ComfyUI 成品超时，请检查服务中的任务 {task_id}")

    async def generate(
        self, job: dict, pet: dict, output_dir: Path,
        persist_remote: PersistRemoteFn, update_progress: ProgressFn,
    ) -> tuple[Path, dict[str, Path]]:
        """执行 job 的参数快照，用 pet 选择默认物种，回调持久化状态并返回本地素材路径。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        config = job.get("generation_config") or default_generation_settings("comfyui")
        base = config.get("comfyui_base_url", self.settings.comfyui_base_url)
        prompts = config["prompts"]
        prompts = prompts.get(pet["species"], prompts)
        remote = dict(job.get("remote_tasks") or {})
        job_id = job["id"]
        seed = int(job_id[:12], 16)

        async def render(stage: str, prompt_key: str, progress: int, target: Path, reference: str | None) -> Path:
            record = remote.get(stage, {})
            if record.get("state") == "complete" and target.is_file():
                return target
            await update_progress(stage, progress)
            if not record.get("provider_id"):
                is_image = stage == "idle"
                kind = "image" if is_image else "video"
                build = image_workflow if is_image else video_workflow
                graph = build(reference, prompts[prompt_key], (config[f"{kind}_width"], config[f"{kind}_height"]),
                              seed + progress, f"pet_wallpaper_demo/{job_id}/{stage}")
                task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"pet-wallpaper-demo/{job_id}/{stage}"))
                # 先记录本次提交的任务 ID，避免重启后重复排队。
                record = remote[stage] = {"state": "submitting", "provider_id": task_id}
                await persist_remote(remote)
                try:
                    queued = await self._json("POST", f"{base}/prompt", json={"prompt": graph, "prompt_id": task_id})
                except ProviderError as exc:
                    # 连接中断时请求可能已被接受，交给历史查询确认。
                    if not isinstance(exc.__cause__, (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError)):
                        raise
                else:
                    if not isinstance(queued.get("prompt_id"), str) or not queued["prompt_id"]:
                        raise ProviderError("ComfyUI 提交任务后未返回任务 ID")
                    record.update(state="running", provider_id=queued["prompt_id"])
                    await persist_remote(remote)
            output = await self._collect(base, record["provider_id"], target)
            if stage == "idle":
                # 视频任务与待机图位于同一台 ComfyUI，直接读取其输出目录。
                filename = output["filename"]
                subfolder = output.get("subfolder")
                path = f"{subfolder}/{filename}" if subfolder else filename
                record["output_reference"] = f"{path} [output]"
            record["state"] = "complete"
            await persist_remote(remote)
            return target

        photo = None
        if not remote.get("idle", {}).get("provider_id"):
            photo = await self._upload(base, Path(job["photo_path"]), f"{job_id}-photo.jpg")
        idle = await render("idle", "image", 20, output_dir / "idle.png", photo)
        reference = remote["idle"].get("output_reference")
        # 旧任务没有记录远端成品路径，仍可使用已下载的待机图恢复。
        if not reference and any(not remote.get(stage, {}).get("provider_id") for stage, _, _ in VIDEO_STAGES):
            reference = await self._upload(base, idle, f"{job_id}-idle.png")
        videos = {}
        for stage, prompt_key, progress in VIDEO_STAGES:
            videos[stage] = await render(stage, prompt_key, progress, output_dir / f"{stage}.mp4", reference)
        return idle, videos
