"""文件用途：通过 ComfyUI API 生成待机图、待机视频和三个交互视频，并恢复远端任务。"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import httpx
from PIL import Image

from .comfyui_workflows import OUTPUT_NODE, image_workflow, video_workflow
from .config import Settings
from .decoration import portrait_prompt, styled_idle_prompt, styled_video_prompt
from .generation_settings import default_generation_settings
from .providers import BaseGenerationProvider, PersistRemoteFn, ProgressFn, ProviderError

# 待机图统一使用固定采样种子。
IDLE_IMAGE_SEED = 49
VIDEO_STAGES = (("idle-video", "idle", 40), ("left", "left", 55), ("center", "center", 70), ("right", "right", 85))
logger = logging.getLogger(__name__)


def _queue_prompt_ids(items: object) -> set[str]:
    """从 ComfyUI 队列条目中提取 prompt_id 集合。"""
    if not isinstance(items, list):
        return set()
    ids: set[str] = set()
    for entry in items:
        if isinstance(entry, (list, tuple)) and len(entry) >= 2 and isinstance(entry[1], str):
            ids.add(entry[1])
    return ids


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
        # 多只宠物同时生成时，每个实例也只承接一个尚未收集结果的新任务。
        self._endpoint_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def close(self) -> None:
        """关闭 ComfyUI HTTP 连接池，无返回值。"""
        await self.client.aclose()

    async def _post_control(self, endpoint: str, **kwargs) -> None:
        """向 ComfyUI 控制接口发送请求，允许空响应体。"""
        try:
            response = await self.client.request("POST", endpoint, timeout=5, **kwargs)
            if response.status_code >= 400:
                raise ProviderError(f"ComfyUI 接口返回 HTTP {response.status_code}")
        except httpx.HTTPError as exc:
            raise ProviderError("无法连接 ComfyUI 发送中断请求") from exc

    async def _cancel_endpoint(self, endpoint: str, prompt_ids: list[str]) -> None:
        """核对指定 ComfyUI 实例队列后，移除排队任务并中断当前运行中的目标任务。"""
        try:
            queue = await self._json("GET", f"{endpoint}/queue", timeout=5)
        except ProviderError as exc:
            logger.warning("查询 ComfyUI 队列状态失败（%s）：%s", endpoint, exc)
            return

        pending_ids = _queue_prompt_ids(queue.get("queue_pending"))
        running_ids = _queue_prompt_ids(queue.get("queue_running"))
        pending = [pid for pid in prompt_ids if pid in pending_ids]
        running = [pid for pid in prompt_ids if pid in running_ids]

        if pending:
            try:
                await self._post_control(f"{endpoint}/queue", json={"delete": pending})
            except ProviderError as exc:
                logger.warning("移除 ComfyUI 排队任务失败（%s）：%s", endpoint, exc)

        for pid in running:
            try:
                await self._post_control(f"{endpoint}/interrupt", json={"prompt_id": pid})
            except ProviderError as exc:
                logger.warning("中断 ComfyUI 运行任务失败（%s, %s）：%s", endpoint, pid, exc)

    async def cancel(self, job: dict) -> None:
        """主动清理远端 ComfyUI 队列中属于该任务的待执行与运行中阶段。"""
        if job.get("status") in {"ready", "failed"}:
            return
        remote = job.get("remote_tasks") or {}
        if not isinstance(remote, dict) or not remote:
            return
        config = job.get("generation_config") or {}
        idle_record = remote.get("idle") if isinstance(remote.get("idle"), dict) else {}
        default_base = config.get("comfyui_base_url") or idle_record.get("base_url") or self.settings.comfyui_base_url

        by_endpoint: dict[str, list[str]] = defaultdict(list)
        for record in remote.values():
            if not isinstance(record, dict) or record.get("state") == "complete":
                continue
            prompt_id = record.get("provider_id")
            if not isinstance(prompt_id, str) or not prompt_id:
                continue
            endpoint = record.get("base_url") or default_base
            if endpoint and prompt_id not in by_endpoint[endpoint]:
                by_endpoint[endpoint].append(prompt_id)

        if by_endpoint:
            await asyncio.gather(
                *(self._cancel_endpoint(endpoint, prompt_ids) for endpoint, prompt_ids in by_endpoint.items())
            )

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
        mime = {".png": "image/png", ".webp": "image/webp"}.get(path.suffix, "image/jpeg")
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
        remote = dict(job.get("remote_tasks") or {})
        idle_record = remote.get("idle", {})
        base = config.get("comfyui_base_url") or idle_record.get("base_url") or self.settings.comfyui_base_url
        prompts = config["prompts"]
        prompts = prompts.get(pet["species"], prompts)
        job_id = job["id"]
        video_seed = int(job_id[:12], 16)
        current_progress = job.get("progress", 0)
        portrait_only = job.get("portrait_only")
        decoration = job.get("decoration")

        async def advance(stage: str, progress: int) -> None:
            nonlocal current_progress
            if progress > current_progress:
                current_progress = progress
                await update_progress(stage, progress)

        async def render(
            endpoint: str, stage: str, prompt_key: str, seed: int, target: Path, reference: str | None,
        ) -> Path:
            record = remote.get(stage) or {}
            if not record.get("provider_id"):
                is_image = stage in {"idle", "portrait"}
                kind = "image" if is_image else "video"
                prompt = prompts[prompt_key]
                if stage == "portrait":
                    prompt = portrait_prompt(prompt)
                elif decoration:
                    prompt = styled_idle_prompt(prompt, decoration, pet["species"]) if is_image else styled_video_prompt(prompt)
                size = (config[f"{kind}_width"], config[f"{kind}_height"])
                prefix = f"pet_wallpaper_demo/{job_id}/{stage}"
                if is_image:
                    accessory_reference = None
                    if decoration and decoration["accessory"] != "none":
                        filename = f"{decoration['accessory']}.webp"
                        accessory_reference = await self._upload(
                            endpoint, self.settings.assets_dir / "decoration" / filename, f"{job_id}-{filename}"
                        )
                    graph = image_workflow(reference, prompt, size, seed, prefix, accessory_reference=accessory_reference)
                else:
                    graph = video_workflow(reference, prompt, size, seed, prefix)
                task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"pet-wallpaper-demo/{job_id}/{stage}"))
                # 提交前落盘实例地址与任务 ID，重启后继续向原实例查询。
                record = remote[stage] = {"state": "submitting", "provider_id": task_id, "base_url": endpoint}
                await persist_remote(remote)
                try:
                    queued = await self._json("POST", f"{endpoint}/prompt", json={"prompt": graph, "prompt_id": task_id})
                except ProviderError as exc:
                    # 连接中断时请求可能已被接受，交给历史查询确认。
                    if not isinstance(exc.__cause__, (httpx.ReadError, httpx.ReadTimeout, httpx.RemoteProtocolError)):
                        raise
                else:
                    if not isinstance(queued.get("prompt_id"), str) or not queued["prompt_id"]:
                        raise ProviderError("ComfyUI 提交任务后未返回任务 ID")
                    record.update(state="running", provider_id=queued["prompt_id"])
                    await persist_remote(remote)
            output = await self._collect(endpoint, record["provider_id"], target)
            if stage == "idle":
                # 两个实例共用输出目录，视频工作流可以直接读取待机图。
                filename = output["filename"]
                subfolder = output.get("subfolder")
                path = f"{subfolder}/{filename}" if subfolder else filename
                record["output_reference"] = f"{path} [output]"
            record["state"] = "complete"
            await persist_remote(remote)
            return target

        image_stage = "portrait" if portrait_only else "idle"
        image_record = remote.get(image_stage, {})
        idle = output_dir / f"{image_stage}.png"
        if image_record.get("state") != "complete" or not idle.is_file():
            photo = None
            if not image_record.get("provider_id"):
                photo = await self._upload(base, Path(job["photo_path"]), f"{job_id}-photo.jpg")
            image_endpoint = image_record.get("base_url", base)
            async with self._endpoint_locks[image_endpoint]:
                await advance(image_stage, 20)
                # 用新任务重试正面照时更换种子，待机图保留原定采样种子。
                image_seed = video_seed if portrait_only else IDLE_IMAGE_SEED
                await render(image_endpoint, image_stage, "image", image_seed, idle, photo)
        if portrait_only:
            return idle, {}
        reference = remote.get("idle", {}).get("output_reference")
        # 旧任务没有记录远端成品路径，仍可使用已下载的待机图恢复。
        if not reference and any(not remote.get(stage, {}).get("provider_id") for stage, _, _ in VIDEO_STAGES):
            reference = await self._upload(base, idle, f"{job_id}-idle.png")
        # 第二实例与当前主实例成对部署。修改主地址后，旧任务的新阶段仍用旧主实例。
        secondary = self.settings.comfyui_secondary_base_url if base == self.settings.comfyui_base_url else ""
        if secondary and any(not remote.get(stage, {}).get("provider_id") for stage, _, _ in VIDEO_STAGES):
            try:
                stats = await self._json("GET", f"{secondary}/system_stats", timeout=5)
                if not stats.get("devices"):
                    raise ProviderError("第二个 ComfyUI 实例没有可用设备")
            except ProviderError:
                logger.warning("第二个 ComfyUI 实例不可用，未提交的视频改用主实例")
                secondary = ""
        endpoints = (base, secondary) if secondary else (base,)

        videos: dict[str, Path] = {}
        pending: deque[tuple[str, str, int]] = deque()
        recovering: dict[str, deque[tuple[str, str, int]]] = defaultdict(deque)
        for stage, prompt_key, seed_offset in VIDEO_STAGES:
            record = remote.get(stage, {})
            target = output_dir / f"{stage}.mp4"
            if record.get("state") == "complete" and target.is_file():
                videos[stage] = target
            elif record.get("provider_id"):
                # 双卡上线前保存的任务没有地址字段，查询原主实例。
                endpoint = record.get("base_url", base)
                recovering[endpoint].append((stage, prompt_key, seed_offset))
            else:
                pending.append((stage, prompt_key, seed_offset))

        started = len(videos)

        async def run_endpoint(endpoint: str) -> None:
            nonlocal started
            saved = recovering[endpoint]
            can_submit = endpoint in endpoints
            while saved or (can_submit and pending):
                async with self._endpoint_locks[endpoint]:
                    # 恢复已提交的任务后，空闲实例从同一队列领取下一个视频。
                    queue = saved if saved else pending
                    if not queue:
                        return
                    stage, prompt_key, seed_offset = queue.popleft()
                    progress = VIDEO_STAGES[started][2]
                    started += 1
                    await advance(stage, progress)
                    target = output_dir / f"{stage}.mp4"
                    videos[stage] = await render(endpoint, stage, prompt_key, video_seed + seed_offset, target, reference)

        tasks = [asyncio.create_task(run_endpoint(endpoint)) for endpoint in dict.fromkeys((*endpoints, *recovering))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return idle, {stage: videos[stage] for stage, _, _ in VIDEO_STAGES}
