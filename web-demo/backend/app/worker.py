"""文件用途：单实例异步任务调度器，负责队列执行、成品验收发布和重启后未完成任务恢复。"""

from __future__ import annotations

import asyncio
import fcntl
import logging
from dataclasses import replace
from pathlib import Path
from shutil import copyfile

from .config import Settings
from .db import DemoDatabase
from .media import AssetValidationError, validate_asset_bundle
from .providers import BaseGenerationProvider, ProviderError, build_provider

logger = logging.getLogger(__name__)


class GenerationWorker:
    """管理所有宠物生成任务的并发执行与 SQLite 状态落盘。"""

    def __init__(self, settings: Settings, db: DemoDatabase, provider: BaseGenerationProvider | None = None):
        self.settings = settings
        self.db = db
        self._providers = {settings.provider: provider} if provider is not None else {}
        self._semaphore = asyncio.Semaphore(2)  # 允许猫狗同时提交时并发推进、先后就绪
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock_handle = None

    def _rel_path(self, path: Path) -> str:
        return path.resolve().relative_to(self.settings.data_dir.resolve()).as_posix()

    def resolve_data_path(self, stored_path: str) -> Path:
        """安全解析数据库中保存的数据目录相对路径，防止路径穿越。"""
        base = self.settings.data_dir.resolve()
        candidate = (base / stored_path).resolve()
        if candidate != base and base not in candidate.parents:
            raise FileNotFoundError("非法文件路径")
        return candidate

    async def start(self) -> None:
        """启动时抢占单实例文件锁，并自动恢复数据库中未完成的任务。"""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.settings.disable_worker_lock:
            lock_path = self.settings.data_dir / ".worker.lock"
            handle = lock_path.open("a+")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.close()
                raise RuntimeError("已有网页 Demo 后端实例在使用该数据目录，请保持单 worker 运行") from exc
            self._lock_handle = handle

        incomplete = self.db.list_incomplete_jobs()
        for job in incomplete:
            self.enqueue(job["id"])

    async def close(self) -> None:
        """关闭调度器并取消本机协程，未完成任务由 SQLite 状态保留以便重启恢复。"""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        for provider in self._providers.values():
            await provider.close()
        if self._lock_handle is not None:
            fcntl.flock(self._lock_handle, fcntl.LOCK_UN)
            self._lock_handle.close()
            self._lock_handle = None

    def enqueue(self, job_id: str) -> None:
        """安排指定任务在后台异步执行（若已在执行则不重复拉起）。"""
        existing = self._tasks.get(job_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._run_job(job_id))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _t, jid=job_id: self._tasks.pop(jid, None))

    def _get_provider(self, mode: str) -> BaseGenerationProvider:
        if mode not in self._providers:
            self._providers[mode] = build_provider(replace(self.settings, provider=mode))
        return self._providers[mode]

    async def cancel_jobs(self, jobs: list[dict]) -> None:
        """取消并等待属于已删除宠物的后台生成任务退出，并通知远端中止未完成任务。"""
        job_ids = [job["id"] for job in jobs]
        tasks = [task for jid in job_ids if (task := self._tasks.get(jid)) is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        active_jobs = [job for job in jobs if job.get("status") not in {"ready", "failed"}]
        if active_jobs:
            await asyncio.gather(
                *(self._cancel_remote_job(job) for job in active_jobs),
                return_exceptions=True,
            )

    async def _cancel_remote_job(self, job: dict) -> None:
        try:
            await self._get_provider(job["provider"]).cancel(job)
        except Exception:
            logger.warning("取消远端生成任务 %s 失败", job.get("id"), exc_info=True)

    async def _run_job(self, job_id: str) -> None:
        async with self._semaphore:
            job = self.db.get_job_any(job_id)
            if not job or job["status"] in {"ready", "failed"}:
                return
            pet = self.db.get_pet_any(job["pet_id"])
            if not pet:
                self.db.fail_job(job_id, error_message="关联的宠物档案不存在")
                return

            # 将相对路径解析为绝对路径传给 provider
            abs_photo = self.resolve_data_path(job["photo_path"])
            job_runtime = {**job, "photo_path": str(abs_photo)}
            work_dir = self.settings.data_dir / "versions" / job_id

            async def persist_remote(remote_tasks: dict) -> None:
                job_runtime["remote_tasks"] = remote_tasks
                self.db.update_job_progress(job_id, status="generating", remote_tasks=remote_tasks)

            async def update_progress(stage: str, progress: int) -> None:
                self.db.update_job_progress(job_id, status="generating", stage=stage, progress=progress)

            try:
                self.db.update_job_progress(job_id, status="generating", stage="idle", progress=max(job["progress"], 5))
                # 任务按提交时的供应商执行，切换设置后仍可恢复原任务。
                mode = job["provider"]
                idle_path, action_paths = await self._get_provider(mode).generate(
                    job_runtime, pet, work_dir, persist_remote, update_progress
                )
                self.db.update_job_progress(job_id, status="generating", stage="validating", progress=96)
                idle_meta, actions_meta = await asyncio.to_thread(
                    validate_asset_bundle, idle_path, action_paths
                )
                generation = job.get("generation_config") or {}
                if mode == "comfyui" and generation:
                    if (idle_meta["width"], idle_meta["height"]) != (generation["image_width"], generation["image_height"]):
                        raise AssetValidationError("ComfyUI 待机图分辨率与任务设置不一致")
                    video_size = (generation["video_width"], generation["video_height"])
                    if "idle-video" not in actions_meta or any(
                        (meta["width"], meta["height"]) != video_size for meta in actions_meta.values()
                    ):
                        raise AssetValidationError("ComfyUI 缺少待机视频或视频分辨率与任务设置不一致")
                # 统一记录相对于 data_dir 的安全路径
                idle_rel = self._rel_path(idle_path)
                for slot, video_path in action_paths.items():
                    actions_meta[slot]["file_path"] = self._rel_path(video_path)
                self.db.publish_version(
                    job_id=job_id,
                    pet_id=pet["id"],
                    idle_image_path=idle_rel,
                    idle_meta=idle_meta,
                    actions_meta=actions_meta,
                    remote_tasks=job_runtime.get("remote_tasks"),
                )
            except asyncio.CancelledError:
                raise
            except (ProviderError, AssetValidationError) as exc:
                self.db.fail_job(
                    job_id,
                    error_message=str(exc),
                    remote_tasks=job_runtime.get("remote_tasks"),
                )
            except Exception:
                logger.exception("生成任务 %s 执行发生未预期异常", job_id)
                self.db.fail_job(
                    job_id,
                    error_message="生成服务处理异常，请检查本机环境或稍后重试",
                    remote_tasks=job_runtime.get("remote_tasks"),
                )
