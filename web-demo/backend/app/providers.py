"""文件用途：定义宠物壁纸生成接口和供应商工厂，包含 Mock 和可灵实现。"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import re
import shutil
import sys
import time
import types
from io import BytesIO
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import quote, urlparse

import httpx
from PIL import Image, ImageOps

from .config import REPO_ROOT, Settings
from .decoration import Decoration, compose_decoration, portrait_prompt, styled_idle_prompt, styled_video_prompt


def _load_algo_presets() -> tuple[dict, dict]:
    """隔离加载 algorithm-lab 中的 PRD 提示词预设，避免与后端自身的 app 包名冲突。"""
    algo_app_dir = REPO_ROOT / "algorithm-lab" / "app"
    pkg_name = "_algo_lab_app"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(algo_app_dir)]  # type: ignore[attr-defined]
        sys.modules[pkg_name] = pkg
        for mod_name in ("video", "wallpaper"):
            spec = importlib.util.spec_from_file_location(f"{pkg_name}.{mod_name}", algo_app_dir / f"{mod_name}.py")
            assert spec is not None and spec.loader is not None
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"{pkg_name}.{mod_name}"] = mod
            spec.loader.exec_module(mod)
    wallpaper_mod = sys.modules[f"{pkg_name}.wallpaper"]
    return wallpaper_mod.IMAGE_PRESETS, wallpaper_mod.VIDEO_PRESET_LOOKUP


ALGO_IMAGE_PRESETS, ALGO_VIDEO_PRESETS = _load_algo_presets()

PersistRemoteFn = Callable[[dict], Awaitable[None]]
ProgressFn = Callable[[str, int], Awaitable[None]]


class ProviderError(Exception):
    """表示生成过程中可呈现给用户的错误信息。"""

    def __init__(self, message: str, resumable: bool = False):
        super().__init__(message)
        self.resumable = resumable


class BaseGenerationProvider:
    """生成供应商抽象接口，约定正面照、确认后的动画与旧版整套生成的返回结构。"""

    async def close(self) -> None:
        return None

    async def cancel(self, job: dict) -> None:
        """通知远端供应商中止未完成任务；默认无需额外操作。"""
        return None

    async def generate(
        self,
        job: dict,
        pet: dict,
        output_dir: Path,
        persist_remote: PersistRemoteFn,
        update_progress: ProgressFn,
    ) -> tuple[Path, dict[str, Path]]:
        """执行 job 与 pet 的生成阶段；回调记录进度，返回图像路径及视频路径映射。

        正面照阶段只输出图像。确认后用原照与装扮生成待机图，供视频阶段参考。
        """
        raise NotImplementedError


class MockGenerationProvider(BaseGenerationProvider):
    """基于本地归档样例素材的模拟生成供应商，支持分段进度、重启续传与失败注入。"""

    STAGE_PROGRESS = {
        "idle": 25,
        "left": 50,
        "center": 72,
        "right": 90,
        "validating": 96,
    }

    def __init__(self, settings: Settings):
        self.settings = settings

    async def generate(
        self,
        job: dict,
        pet: dict,
        output_dir: Path,
        persist_remote: PersistRemoteFn,
        update_progress: ProgressFn,
    ) -> tuple[Path, dict[str, Path]]:
        """用本地素材和可控延迟模拟 job 的阶段，返回产出图像与视频的路径。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        species = pet["species"]
        sample_dir = self.settings.assets_dir / "samples" / species
        if not sample_dir.is_dir():
            raise ProviderError(f"缺少 {species} 样例素材目录，请先运行素材准备脚本")

        options = job.get("mock_options") or {}
        total_delay = float(options.get("delay_seconds", self.settings.mock_delay_seconds))
        total_delay = max(0.05, min(total_delay, 120.0))
        fail_stage = options.get("fail_stage")
        fail_message = str(options.get("fail_message") or "模拟生成失败，请重试")

        if job.get("portrait_only"):
            await update_progress("portrait", 45)
            await asyncio.sleep(min(total_delay / 4, 1.0))
            if fail_stage in {"portrait", "any"}:
                raise ProviderError(fail_message)
            target = output_dir / "portrait-source.png"
            artwork = self.settings.assets_dir / "decoration" / f"mock-{species}.webp"
            with Image.open(artwork) as source:
                pet_image = ImageOps.contain(source.convert("RGBA"), (960, 800), Image.Resampling.LANCZOS)
            image = Image.new("RGBA", (1920, 1080))
            image.alpha_composite(pet_image, ((image.width - pet_image.width) // 2, 975 - pet_image.height))
            image.save(target)
            return target, {}

        remote = dict(job.get("remote_tasks") or {})
        stages = [
            ("idle", sample_dir / "idle.jpg", output_dir / "idle.jpg"),
            ("left", sample_dir / "left.mp4", output_dir / "left.mp4"),
            ("center", sample_dir / "center.mp4", output_dir / "center.mp4"),
            ("right", sample_dir / "right.mp4", output_dir / "right.mp4"),
        ]
        decoration = job.get("decoration")
        idle_path = output_dir / "idle.jpg"
        if decoration:
            idle_path = output_dir / "idle.png"
            stages[0] = ("idle", Path(job["photo_path"]), idle_path)
            stages.insert(1, ("idle-video", idle_path, output_dir / "idle-video.mp4"))
        per_stage_delay = total_delay / len(stages)

        for stage_key, src_file, dst_file in stages:
            record = remote.get(stage_key, {})
            if record.get("state") == "complete" and dst_file.is_file():
                continue

            if not src_file.is_file():
                raise ProviderError(f"样例素材文件缺失: {src_file.name}")

            if not record.get("provider_id"):
                record = {
                    "state": "running",
                    "provider_id": f"mock-{job['id'][:8]}-{stage_key}",
                }
                remote[stage_key] = record
                await persist_remote(remote)

            await update_progress(stage_key, self.STAGE_PROGRESS.get(stage_key, 25))
            await asyncio.sleep(per_stage_delay)

            if fail_stage in {stage_key, "any"}:
                record["state"] = "failed"
                remote[stage_key] = record
                await persist_remote(remote)
                raise ProviderError(fail_message)

            if stage_key == "idle" and decoration:
                with Image.open(src_file) as source:
                    pet_image = ImageOps.contain(source.convert("RGBA"), (960, 800), Image.Resampling.LANCZOS)
                layer = Image.new("RGBA", (1920, 1080))
                layer.alpha_composite(pet_image, ((layer.width - pet_image.width) // 2, (layer.height - pet_image.height) // 2))
                compose_decoration(layer, self.settings.assets_dir, Decoration.model_validate(decoration)).save(dst_file)
            elif stage_key == "idle-video":
                await self._make_mock_idle(src_file, dst_file)
            else:
                shutil.copyfile(src_file, dst_file)
            record["state"] = "complete"
            remote[stage_key] = record
            await persist_remote(remote)

        await update_progress("validating", self.STAGE_PROGRESS["validating"])
        return (
            idle_path,
            {
                "left": output_dir / "left.mp4",
                "center": output_dir / "center.mp4",
                "right": output_dir / "right.mp4",
                **({"idle-video": output_dir / "idle-video.mp4"} if decoration else {}),
            },
        )

    async def _make_mock_idle(self, source: Path, target: Path) -> None:
        temporary = target.with_suffix(".part")
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(source), "-t", "2",
            "-vf", "scale=960:-2", "-r", "25", "-an", "-c:v", "libx264", "-threads", "2",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", str(temporary),
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            if await process.wait():
                raise ProviderError("模拟待机视频生成失败")
            temporary.replace(target)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            temporary.unlink(missing_ok=True)


class KlingGenerationProvider(BaseGenerationProvider):
    """接入可灵 API 的真实生成供应商：先生成待机图，再用同一张待机图生成左/中/右三段动作视频。"""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.client = client or httpx.AsyncClient(timeout=90)

    async def close(self) -> None:
        await self.client.aclose()

    def _safe_message(self, value: object) -> str:
        text = str(value)
        if self.settings.kling_api_key:
            text = text.replace(self.settings.kling_api_key, "[已隐藏]")
        return re.sub(r"https?://\S+", "[远端链接]", text)[:240]

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        if not self.settings.kling_api_key:
            raise ProviderError("未配置 KLING_API_KEY，无法调用可灵生成服务")
        try:
            response = await self.client.request(
                method,
                self.settings.kling_base_url + path,
                headers={"Authorization": f"Bearer {self.settings.kling_api_key}"},
                **kwargs,
            )
        except httpx.HTTPError as exc:
            if method == "POST":
                raise ProviderError("提交可灵任务时网络连接中断，请先核对控制台后再重试") from exc
            raise ProviderError("查询可灵任务网络异常，请稍后重试", True) from exc

        if response.status_code >= 500 or response.status_code == 408:
            if method == "POST":
                raise ProviderError(f"可灵提交接口异常（HTTP {response.status_code}），请核对控制台")
            raise ProviderError(f"可灵查询暂不可用（HTTP {response.status_code}）", True)
        if response.status_code >= 400:
            raise ProviderError(f"可灵拒绝请求（HTTP {response.status_code}），请检查密钥与额度")

        try:
            payload = response.json()
            if not isinstance(payload, dict) or "code" not in payload:
                raise ValueError("响应格式无效")
        except ValueError as exc:
            raise ProviderError("可灵响应无法解析", method == "GET") from exc

        if str(payload.get("code")) != "0":
            raise ProviderError(
                f"可灵返回错误 {payload.get('code')}：{self._safe_message(payload.get('message', '请求失败'))}",
                method == "GET",
            )
        return payload

    async def _submit_idle(
        self, photo_path: Path, species: str, external_id: str, prompt: str | None = None,
        *, accessory_path: Path | None = None,
    ) -> str:
        preset_key = "cat-idle" if species == "cat" else "dog-idle"
        prompt = prompt or ALGO_IMAGE_PRESETS[preset_key]["prompt"]
        images = [{"image": base64.b64encode(photo_path.read_bytes()).decode("ascii")}]
        if accessory_path:
            with Image.open(accessory_path) as accessory, BytesIO() as buffer:
                accessory.save(buffer, format="PNG")
                images.append({"image": base64.b64encode(buffer.getvalue()).decode("ascii")})
        payload = {
            "model_name": "kling-v3-omni",
            "prompt": prompt,
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "n": 1,
            "external_task_id": external_id,
            "image_list": images,
            "result_type": "single",
        }
        result = await self._request("POST", "/v1/images/omni-image", json=payload)
        task_id = (result.get("data") or {}).get("task_id")
        if not task_id:
            raise ProviderError("可灵图片响应缺少 task_id")
        return str(task_id)

    async def _query_idle(self, task_id: str) -> tuple[str, str | None, str]:
        result = await self._request("GET", f"/v1/images/omni-image/{quote(task_id, safe='')}")
        task = result.get("data")
        if not isinstance(task, dict):
            raise ProviderError("可灵图片查询结构异常", True)
        state = task.get("task_status")
        images = (task.get("task_result") or {}).get("images") or []
        url = images[0].get("url") if images else None
        msg = self._safe_message(task.get("task_status_msg", ""))
        return str(state or ""), str(url) if url else None, msg

    async def _submit_action_video(
        self, idle_path: Path, species: str, direction: str, prompt: str | None = None
    ) -> str:
        preset_key = f"{species}-{direction}"
        prompt = prompt or ALGO_VIDEO_PRESETS[preset_key]["prompt"]
        encoded = base64.b64encode(idle_path.read_bytes()).decode("ascii")
        # 严格复用同一张待机图作为首帧与尾帧
        contents = [
            {"type": "prompt", "text": prompt},
            {"type": "first_frame", "url": encoded},
            {"type": "last_frame", "url": encoded},
        ]
        settings = {"duration": 4, "resolution": "1080p", "multi_shot": False}
        result = await self._request("POST", "/image-to-video/kling-3.0", json={"contents": contents, "settings": settings})
        task_id = (result.get("data") or {}).get("id")
        if not task_id:
            raise ProviderError("可灵视频响应缺少任务 ID")
        return str(task_id)

    async def _query_video(self, task_id: str) -> tuple[str, str | None, str]:
        result = await self._request("GET", "/tasks", params={"task_ids": task_id})
        data = result.get("data")
        if not isinstance(data, list):
            raise ProviderError("可灵视频查询结构异常", True)
        task = next((item for item in data if str(item.get("id")) == task_id), None)
        if not task:
            raise ProviderError("未在可灵查询到该视频任务", True)
        state = task.get("status")
        outputs = task.get("outputs") or []
        url = next((item.get("url") for item in outputs if item.get("type") == "video"), None)
        msg = self._safe_message(task.get("message", ""))
        return str(state or ""), str(url) if url else None, msg

    async def _download_file(self, kind: str, url: str, target_stem: Path) -> Path:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ProviderError("供应商返回的下载地址格式不合法")
        limit = 100 * 1024 * 1024 if kind == "video" else 15 * 1024 * 1024
        tmp = target_stem.with_suffix(".part")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as downloader:
                async with downloader.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = 0
                    with tmp.open("wb") as handle:
                        async for chunk in resp.aiter_bytes():
                            total += len(chunk)
                            if total > limit:
                                raise ProviderError("下载成品体积超出限制")
                            handle.write(chunk)
            if kind == "video":
                with tmp.open("rb") as handle:
                    header = handle.read(32)
                if len(header) < 12 or header[4:8] != b"ftyp":
                    raise ProviderError("下载的视频文件不是有效 MP4")
                final_path = target_stem.with_suffix(".mp4")
            else:
                with Image.open(tmp) as img:
                    img.verify()
                    fmt = img.format
                if fmt not in {"JPEG", "PNG"}:
                    raise ProviderError("下载的待机图不是 JPEG 或 PNG")
                final_path = target_stem.with_suffix(".png" if fmt == "PNG" else ".jpg")
            tmp.replace(final_path)
            return final_path
        finally:
            tmp.unlink(missing_ok=True)

    async def _poll_and_download(
        self,
        kind: str,
        task_id: str,
        target_stem: Path,
        query_fn,
    ) -> Path:
        deadline = time.monotonic() + self.settings.kling_task_timeout
        consecutive_errors = 0
        while time.monotonic() < deadline:
            try:
                state, url, msg = await query_fn(task_id)
                consecutive_errors = 0
            except ProviderError as exc:
                consecutive_errors += 1
                if not exc.resumable or consecutive_errors >= 5:
                    raise
                await asyncio.sleep(self.settings.kling_poll_seconds)
                continue

            if state in {"succeed", "succeeded"}:
                if not url:
                    raise ProviderError("任务已完成但下载地址尚未就绪", True)
                return await self._download_file(kind, url, target_stem)
            if state == "failed":
                raise ProviderError(msg or "可灵生成失败")
            if state not in {"submitted", "processing"}:
                raise ProviderError(f"可灵返回未知状态: {state}", True)
            await asyncio.sleep(self.settings.kling_poll_seconds)
        raise ProviderError("等待可灵生成超时，请稍后重试恢复查询", True)

    async def generate(
        self,
        job: dict,
        pet: dict,
        output_dir: Path,
        persist_remote: PersistRemoteFn,
        update_progress: ProgressFn,
    ) -> tuple[Path, dict[str, Path]]:
        """生成或恢复可灵 job，返回本地待机图和使用该图生成的动作视频路径。"""
        output_dir.mkdir(parents=True, exist_ok=True)
        remote = dict(job.get("remote_tasks") or {})
        prompts = (job.get("generation_config") or {}).get("prompts", {})

        # 正面照使用独立记录，旧任务仍以 idle 作为生图阶段。
        portrait_only = job.get("portrait_only")
        decoration = job.get("decoration")
        image_stage = "portrait" if portrait_only else "idle"
        idle_rec = remote.get(image_stage, {})
        idle_path: Path | None = None
        if idle_rec.get("state") == "complete" and idle_rec.get("file"):
            candidate = output_dir / idle_rec["file"]
            if candidate.is_file():
                idle_path = candidate

        if idle_path is None:
            await update_progress(image_stage, 20)
            if idle_rec.get("state") == "submitting" and not idle_rec.get("provider_id"):
                raise ProviderError("待机图提交时服务中断，请先在可灵控制台确认后再重新发起")
            if not idle_rec.get("provider_id"):
                idle_rec = {"state": "submitting", "external_id": f"{job['id']}-{image_stage}"}
                remote[image_stage] = idle_rec
                await persist_remote(remote)
                prompt = prompts.get("image") or ALGO_IMAGE_PRESETS[f"{pet['species']}-idle"]["prompt"]
                if portrait_only:
                    prompt = portrait_prompt(prompt)
                elif decoration:
                    prompt = styled_idle_prompt(prompt, decoration, pet["species"])
                accessory_path = None
                if decoration and decoration["accessory"] != "none":
                    accessory_path = self.settings.assets_dir / "decoration" / f"{decoration['accessory']}.webp"
                provider_id = await self._submit_idle(
                    Path(job["photo_path"]), pet["species"], idle_rec["external_id"], prompt,
                    accessory_path=accessory_path,
                )
                idle_rec.update(state="running", provider_id=provider_id)
                await persist_remote(remote)

            idle_path = await self._poll_and_download(
                "image", idle_rec["provider_id"], output_dir / image_stage, self._query_idle
            )
            idle_rec.update(state="complete", file=idle_path.name)
            remote[image_stage] = idle_rec
            await persist_remote(remote)

        if portrait_only:
            return idle_path, {}

        # 确认后的新任务额外生成待机视频，旧任务继续恢复原来的三个热区。
        action_paths: dict[str, Path] = {}
        stage_progress = {"left": 45, "center": 70, "right": 90}
        if decoration:
            stage_progress = {"idle-video": 30, **stage_progress}
        for direction, progress in stage_progress.items():
            rec = remote.get(direction, {})
            if rec.get("state") == "complete" and rec.get("file"):
                existing = output_dir / rec["file"]
                if existing.is_file():
                    action_paths[direction] = existing
                    continue

            await update_progress(direction, progress)
            if rec.get("state") == "submitting" and not rec.get("provider_id"):
                raise ProviderError(f"{direction} 动作提交时服务中断，请核对控制台后再重新生成")
            if not rec.get("provider_id"):
                rec = {"state": "submitting", "external_id": f"{job['id']}-{direction}"}
                remote[direction] = rec
                await persist_remote(remote)
                prompt_key = "idle" if direction == "idle-video" else direction
                prompt = prompts.get(prompt_key)
                if decoration:
                    fallback = ALGO_VIDEO_PRESETS.get(f"{pet['species']}-{prompt_key}", {}).get(
                        "prompt", "宠物保持正面姿态，自然眨眼和呼吸，首尾姿态一致。"
                    )
                    prompt = styled_video_prompt(prompt or fallback)
                provider_id = await self._submit_action_video(idle_path, pet["species"], prompt_key, prompt)
                rec.update(state="running", provider_id=provider_id)
                remote[direction] = rec
                await persist_remote(remote)

            video_path = await self._poll_and_download(
                "video", rec["provider_id"], output_dir / direction, self._query_video
            )
            rec.update(state="complete", file=video_path.name)
            remote[direction] = rec
            await persist_remote(remote)
            action_paths[direction] = video_path

        await update_progress("validating", 96)
        return idle_path, action_paths


def build_provider(settings: Settings) -> BaseGenerationProvider:
    """根据运行配置 settings 创建并返回网页 Demo 的生成供应商实例。"""
    if settings.provider == "mock":
        return MockGenerationProvider(settings)
    if settings.provider == "kling":
        return KlingGenerationProvider(settings)
    if settings.provider == "comfyui":
        from .comfyui import ComfyUIGenerationProvider

        return ComfyUIGenerationProvider(settings)
    raise ValueError(f"不支持的供应商模式: {settings.provider}")
