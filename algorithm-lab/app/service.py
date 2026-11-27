"""文件用途：执行单任务和并发图生图批次，保存素材版本并安全恢复任务。"""

import asyncio
import fcntl
import logging
import time
import uuid
from datetime import datetime
from shutil import copyfile, rmtree

from .billing import aggregate_costs
from .config import Settings
from .image import DEFAULT_IMAGE_OPTIONS, MAX_IMAGE_REFERENCES, ImageOptions
from .kling import KlingProvider, ProviderError, SubmissionUnknown
from .storage import FrameSource, JobStore, now
from .video import DEFAULT_VIDEO_OPTIONS, VideoOptions


IMAGE_BATCH_CONCURRENCY = 3  # 同批最多同时执行的独立图片任务数。
QUOTA_CACHE_TTL = 60.0  # 额度接口结果本机缓存时长，避免频繁请求。
QUOTA_MIN_INTERVAL = 2.0  # 遵守可灵 /account/costs 接口 QPS <= 1 限制。
logger = logging.getLogger(__name__)


class JobConflict(Exception):
    """表示重复执行、输入过期或人工核对未完成等状态冲突。"""


class JobService:
    """编排本地任务；参数为配置和可替换的供应商，一次执行一个单任务或一个图片批次。"""

    def __init__(self, settings: Settings, provider: KlingProvider):
        self.settings = settings
        self.provider = provider
        self.store = JobStore(settings.data_dir)
        self.task: asyncio.Task | None = None  # 当前任务或批次的执行协程。
        self.active_id: str | None = None
        self.mutation_lock = asyncio.Lock()  # 串行化创建、重做及继续请求。
        self.process_lock = None  # 跨进程锁，禁止多个 worker 同时管理 JSON。
        self._quota_lock = asyncio.Lock()
        self._quota_cache: dict | None = None
        self._quota_fetched_at: float = 0.0
        self._quota_last_attempt_at: float = 0.0
        self._quota_stale: bool = True

    def invalidate_quota_cache(self) -> None:
        """标记额度缓存失效；无参数，无返回值，下次读取时向可灵刷新。"""
        self._quota_stale = True

    def local_spend_summary(self) -> dict:
        """汇总本机历史记录中的生成花费；无参数，返回总计、今日及分类汇总。"""
        local_today = datetime.now().astimezone().date()
        all_costs, today_costs, image_costs, video_costs = [], [], [], []
        recorded_jobs = 0
        recorded_attempts = 0
        for job in self.store.all():
            job_has_cost = False
            for stage in job.get("stages", {}).values():
                for attempt in stage.get("attempts", []):
                    cost = attempt.get("cost")
                    if not isinstance(cost, dict):
                        continue
                    job_has_cost = True
                    recorded_attempts += 1
                    all_costs.append(cost)
                    if job.get("kind") == "image":
                        image_costs.append(cost)
                    elif job.get("kind") == "video":
                        video_costs.append(cost)
                    stamp = attempt.get("finished_at") or attempt.get("created_at")
                    if isinstance(stamp, str):
                        try:
                            if datetime.fromisoformat(stamp).astimezone().date() == local_today:
                                today_costs.append(cost)
                        except ValueError:
                            pass
            if job_has_cost:
                recorded_jobs += 1
        return {
            "total": aggregate_costs(all_costs),
            "today": aggregate_costs(today_costs),
            "image": aggregate_costs(image_costs),
            "video": aggregate_costs(video_costs),
            "recorded_jobs": recorded_jobs,
            "recorded_attempts": recorded_attempts,
        }

    async def get_quota(self, *, force_refresh: bool = False) -> dict:
        """获取可灵账户剩余资源包额度与本机累计花费；参数 force_refresh 控制是否主动刷新。"""
        local_spend = self.local_spend_summary()
        if not self.settings.api_key:
            return {
                "configured": False, "available": False, "packs": [], "online_packs": [],
                "error": None, "fetched_at": None, "cached": False, "local_spend": local_spend,
            }
        if not hasattr(self.provider, "account_costs"):
            return {
                "configured": True, "available": False, "packs": [], "online_packs": [],
                "error": "当前供应商不支持额度查询", "fetched_at": None, "cached": False, "local_spend": local_spend,
            }
        async with self._quota_lock:
            now_mono = time.monotonic()
            cache_valid = (
                self._quota_cache is not None
                and not force_refresh
                and not self._quota_stale
                and (now_mono - self._quota_fetched_at) < QUOTA_CACHE_TTL
            )
            throttled = self._quota_cache is not None and (now_mono - self._quota_last_attempt_at) < QUOTA_MIN_INTERVAL
            if cache_valid or throttled:
                return {**self._quota_cache, "local_spend": local_spend, "cached": True}
            self._quota_last_attempt_at = now_mono
            try:
                packs = await self.provider.account_costs()
            except ProviderError as exc:
                return {
                    "configured": True,
                    "available": False,
                    "packs": self._quota_cache["packs"] if self._quota_cache else [],
                    "online_packs": self._quota_cache["online_packs"] if self._quota_cache else [],
                    "error": str(exc),
                    "fetched_at": self._quota_cache["fetched_at"] if self._quota_cache else None,
                    "cached": False,
                    "local_spend": local_spend,
                }
            online_packs = [pack for pack in packs if pack.get("status") == "online"]
            payload = {
                "configured": True,
                "available": True,
                "packs": packs,
                "online_packs": online_packs,
                "error": None,
                "fetched_at": now(),
            }
            self._quota_cache = payload
            self._quota_fetched_at = time.monotonic()
            self._quota_stale = False
            return {**payload, "local_spend": local_spend, "cached": False}

    @property
    def busy(self) -> bool:
        """返回是否有流程正在执行；无参数，返回布尔值。"""
        return self.task is not None and not self.task.done()

    async def start(self) -> None:
        """启动时持锁并恢复任务；无参数，无返回值，不重新提交状态不明的付费请求。"""
        self.process_lock = (self.settings.data_dir / ".service.lock").open("a+")
        try:
            fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self.process_lock.close()
            self.process_lock = None
            raise RuntimeError("已有服务管理此数据目录，请使用单 worker 启动") from exc
        resumable = []
        for job in self.store.all():
            if job["status"] not in {"queued", "running"}:
                continue
            ambiguous = False
            for stage in job["stages"].values():
                if not stage["attempts"]:
                    continue
                attempt = stage["attempts"][-1]
                if attempt["state"] == "submitting" and not attempt.get("provider_id"):
                    attempt["state"] = stage["state"] = "needs_review"
                    attempt["error"] = "服务在提交期间中断，请先核对可灵控制台中的任务"
                    ambiguous = True
            if ambiguous:
                job["status"] = "needs_review"
                job["error"] = "提交结果待核对，未自动创建新任务"
                self.store.save(job)
            else:
                resumable.append(job)
        if resumable:
            self.active_id = resumable[0]["id"]
            self.task = asyncio.create_task(self._recover(resumable))

    async def _recover(self, jobs: list[dict]) -> None:
        groups = {}
        for job in jobs:
            groups.setdefault(job.get("batch_id") or job["id"], []).append(job)
        for group in groups.values():
            group.sort(key=lambda job: job.get("batch_index", 0))
            self.active_id = group[0]["id"]
            if group[0].get("batch_id"):
                await self._run_image_batch(group)
            else:
                job = group[0]
                await self._run(job["id"], next(iter(job["stages"])))

    async def _run_image_batch(self, jobs: list[dict]) -> None:
        slots = asyncio.Semaphore(IMAGE_BATCH_CONCURRENCY)

        async def run_image(job_id: str) -> None:
            async with slots:
                await self._run(job_id, "idle")

        # 单个任务失败只影响自身，其余任务继续运行并独立保存结果。
        results = await asyncio.gather(*(run_image(job["id"]) for job in jobs), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("图片批次中的任务无法写入状态", exc_info=result)

    async def close(self) -> None:
        """取消本机等待并释放资源；无参数，无返回值，已记录远端 ID 保留供重启恢复。"""
        if self.busy:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        await self.provider.close()
        if self.process_lock:
            fcntl.flock(self.process_lock, fcntl.LOCK_UN)
            self.process_lock.close()

    def ensure_available(self) -> None:
        """校验密钥和空闲状态；无参数，无返回值，不可执行时抛出异常。"""
        if not self.settings.api_key:
            raise ProviderError("请先在本机 .env 配置 KLING_API_KEY 并重启服务")
        if self.busy:
            raise JobConflict("已有任务执行中，请等待当前流程结束")

    def _queue(self, job: dict, stage: str) -> None:
        job.update(status="queued", active_stage=stage, pending_stages=[stage], error=None)
        self.store.save(job)

    def _schedule(self, job: dict, stage: str) -> None:
        self._queue(job, stage)
        self.active_id = job["id"]
        self.task = asyncio.create_task(self._run(job["id"], stage))

    async def create(self, photo: bytes | None, video_options: VideoOptions = DEFAULT_VIDEO_OPTIONS, *,
                     video_prompt: str | None = None, tail_photo: bytes | None = None,
                     image_prompt: str | None = None, idle_source: FrameSource | None = None,
                     image_options: ImageOptions = DEFAULT_IMAGE_OPTIONS,
                     additional_photos: list[bytes] | None = None,
                     video_references: list[bytes] | None = None,
                     tail_source: FrameSource | None = None, preset: str | None = None) -> dict:
        """按提示词创建任务；参数含首图、额外参考图或素材来源、生成设置和可选尾帧，返回任务状态。"""
        async with self.mutation_lock:
            self.ensure_available()
            job = self._prepare(uuid.uuid4().hex, photo, video_options, video_prompt=video_prompt,
                                tail_photo=tail_photo, image_prompt=image_prompt, idle_source=idle_source,
                                image_options=image_options, additional_photos=additional_photos,
                                video_references=video_references, tail_source=tail_source, preset=preset)
            self._schedule(job, next(iter(job["stages"])))
            return job

    async def create_image_batch(self, photos: list[bytes], prompt: str, options: ImageOptions, *,
                                 style_photo: bytes | None = None) -> list[dict]:
        """创建图生图批次；参数为主体图、共用提示词和参数、可选姿态风格图，返回各任务状态。"""
        if not 1 <= len(photos) <= MAX_IMAGE_REFERENCES:
            raise ValueError("图片数量超出单批范围")
        async with self.mutation_lock:
            self.ensure_available()
            batch_id = uuid.uuid4().hex
            ids = [uuid.uuid4().hex for _ in photos]
            jobs = []
            try:
                for index, (job_id, photo) in enumerate(zip(ids, photos), start=1):
                    job = self._prepare(job_id, photo, image_prompt=prompt, image_options=options)
                    if style_photo is not None:
                        # 保存独立底图副本，供每个任务查询恢复或按原参数重做。
                        directory = self.store.directory(job_id, "image")
                        (directory / "style.jpg").write_bytes(style_photo)
                        job["input"]["style_file"] = "style.jpg"
                    job.update(batch_id=batch_id, batch_index=index)
                    self._queue(job, "idle")
                    jobs.append(job)
            except Exception:
                # 全批落盘之后才启动生成；准备失败时清理本次新建的目录。
                for job_id in ids:
                    rmtree(self.store.directory(job_id, "image"), ignore_errors=True)
                raise
            self.active_id = jobs[0]["id"]
            self.task = asyncio.create_task(self._run_image_batch(jobs))
            return jobs

    def _prepare(self, job_id: str, photo: bytes | None, video_options: VideoOptions = DEFAULT_VIDEO_OPTIONS, *,
                 video_prompt: str | None = None, tail_photo: bytes | None = None,
                 image_prompt: str | None = None, idle_source: FrameSource | None = None,
                 image_options: ImageOptions = DEFAULT_IMAGE_OPTIONS, additional_photos: list[bytes] | None = None,
                 video_references: list[bytes] | None = None,
                 tail_source: FrameSource | None = None, preset: str | None = None) -> dict:
        if (image_prompt is None) == (video_prompt is None):
            raise ValueError("请选择一种生成任务")
        if (photo is None) == (idle_source is None) or (image_prompt is not None and idle_source is not None):
            raise ValueError("请选择一个图片来源")
        kind = "image" if image_prompt is not None else "video"
        stage = "idle" if kind == "image" else "video"
        input_file = "original.jpg" if kind == "image" else "first.jpg"
        source = None
        if idle_source is not None:
            source, source_record = self.store.frame_source(idle_source)
            input_file = f"first{source.suffix}"
        tail_path = None
        if tail_source is not None:
            tail_path, tail_record = self.store.frame_source(tail_source)
        directory = self.store.directory(job_id, kind)
        directory.mkdir(parents=True)
        if source is not None:
            copyfile(source, directory / input_file)
        elif photo is not None:
            (directory / input_file).write_bytes(photo)
        job = {
            "id": job_id, "created_at": now(), "status": "queued", "error": None,
            "kind": kind,  # 决定任务目录和测试页。
            "input": {"file": input_file, "version": 1},
            "video_options": video_options.model_dump(),
            "stages": {stage: {"state": "pending", "stale": False, "current": None, "attempts": []}},
        }
        if preset is not None:
            job["preset"] = preset  # 保留所采用的 PRD 素材名称，实际参数可独立调整。
        if kind == "image":
            job["image_prompt"] = image_prompt
            job["image_options"] = image_options.model_dump()  # 重做时读取原设置。
            reference_files = []  # 按提示词编号保存第 2 张及后续参考图。
            for number, content in enumerate(additional_photos or [], start=2):
                name = f"reference-{number}.jpg"
                (directory / name).write_bytes(content)
                reference_files.append(name)
            job["input"]["reference_files"] = reference_files
        if kind == "video":
            job["video_prompt"] = video_prompt
            reference_files = []  # 额外视频参考图按上传顺序保存，供重试与重做使用。
            for number, content in enumerate(video_references or [], start=1):
                name = f"video-reference-{number}.jpg"
                (directory / name).write_bytes(content)
                reference_files.append(name)
            job["input"]["video_reference_files"] = reference_files
            if source is not None:
                # 保存来源标识，同时在视频目录保留独立的首帧副本。
                job["input"]["idle_source"] = source_record
            if tail_path is not None:
                name = f"tail{tail_path.suffix}"
                copyfile(tail_path, directory / name)
                job["input"].update(tail_file=name, tail_source=tail_record)
            elif tail_photo is not None:
                (directory / "tail.jpg").write_bytes(tail_photo)
                job["input"]["tail_file"] = "tail.jpg"
        return job

    async def retry(self, job_id: str, stage: str) -> dict:
        """重做或恢复单个阶段；参数为任务 ID 与阶段，返回状态；原任务可查询时复用其 ID。"""
        async with self.mutation_lock:
            self.ensure_available()
            job = self.store.load(job_id)
            if job["status"] == "needs_review":
                raise JobConflict("请先核对提交状态，不能直接再次付费生成")
            if stage not in job["stages"]:
                raise JobConflict("该任务不包含此步骤")
            self._schedule(job, stage)
            return job

    async def reconcile(self, job_id: str, stage: str, provider_id: str | None, not_created: bool) -> dict:
        """处理不明提交；参数为阶段、控制台任务 ID 或未创建确认，返回状态并仅继续当前步骤。"""
        async with self.mutation_lock:
            self.ensure_available()
            job = self.store.load(job_id)
            if stage not in job["stages"]:
                raise JobConflict("该任务不包含此步骤")
            selected = job["stages"][stage]
            if selected["state"] != "needs_review":
                raise JobConflict("该步骤不需要人工核对")
            attempt = selected["attempts"][-1]
            if provider_id:
                # 绑定前只读查询核实；查询失败时保持待核对，不创建新任务。
                await self._query(job, stage, provider_id)
                attempt.update(provider_id=provider_id, state="running", resumable=True, error=None)
            elif not_created:
                attempt.update(state="failed", resumable=False, error="用户已核对未创建，允许新尝试")
            selected["state"] = "failed"
            self._schedule(job, stage)
            return job

    async def _query(self, job: dict, stage: str, provider_id: str):
        """按任务所用接口查询；参数为任务、阶段和远端 ID，返回远端状态。"""
        options = {"image_model": job.get("image_options", {}).get("model")}
        if stage == "video" and job.get("video_options", {}).get("model") == "kling-3.0-omni":
            options["video_model"] = "kling-3.0-omni"
        return await self.provider.query(stage, provider_id, **options)

    async def _run(self, job_id: str, stage: str) -> None:
        job = self.store.load(job_id)
        try:
            # 结果与空计划同时落盘，防止完成瞬间重启重复生成。
            if job["pending_stages"]:
                job.update(status="running", active_stage=stage)
                self.store.save(job)
                await self._step(job, stage)
            job.update(status="complete", active_stage=None, error=None)
            self.store.save(job)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            selected = job["stages"][stage]
            ambiguous = isinstance(exc, SubmissionUnknown)
            state = "needs_review" if ambiguous else "failed"
            # 非预期错误也不得丢失 submitting 标记，否则重启可能重复付费。
            attempt = selected["attempts"][-1] if selected["attempts"] else None
            if attempt and attempt["state"] == "submitting" and not attempt.get("provider_id") and not isinstance(exc, ProviderError):
                state = "needs_review"
            error = str(exc) if isinstance(exc, ProviderError) else "本机任务处理失败，请检查存储空间或后端日志"
            if attempt:
                attempt.update(state=state, error=error, resumable=bool(getattr(exc, "resumable", False)))
            selected["state"] = state
            job.update(status=state, active_stage=stage, error=error)
            self.store.save(job)

    async def _step(self, job: dict, key: str) -> None:
        selected = job["stages"][key]
        last = selected["attempts"][-1] if selected["attempts"] else None
        resume = last and last.get("provider_id") and (last["state"] == "running" or
                                                       (last["state"] == "failed" and last.get("resumable")))
        if resume:
            attempt = last
            attempt.update(state="running", error=None)
            selected["state"] = "running"
        else:
            attempt = {
                "number": len(selected["attempts"]) + 1, "state": "preparing", "provider_id": None,
                "external_id": f"{job['id']}-{key}-{len(selected['attempts']) + 1}",
                "inputs": {"input": job["input"]["version"]}, "output": None, "error": None,
                "resumable": False, "created_at": now(),
            }
            selected["attempts"].append(attempt)
            selected.update(state="running", stale=selected["current"] is not None)
            self.store.save(job)
            directory = self.store.directory(job["id"], job["kind"])
            references = [directory / name for name in self.store.reference_names(job)]
            if tail := job["input"].get("tail_file"):
                references.append(directory / tail)
            video_options = VideoOptions.model_validate(job["video_options"]) if key == "video" else None
            if key == "video" and video_options.model == "kling-3.0-omni":
                if video_options.frame_mode == "first_last" and not job["input"].get("tail_file"):
                    references.append(references[0])  # 未选尾帧时按现有行为复用首帧。
                references.extend(directory / name for name in job["input"].get("video_reference_files", []))
            image_options = ImageOptions.model_validate(job["image_options"]) if key == "idle" else None
            # 先落盘 submitting，再进行唯一一次付费 POST。
            attempt["state"] = "submitting"
            self.store.save(job)
            attempt["provider_id"] = await self.provider.submit(
                key, references, attempt["external_id"], video_options=video_options,
                video_prompt=job.get("video_prompt"), image_prompt=job.get("image_prompt"), image_options=image_options,
            )
            attempt["state"] = "running"
        self.store.save(job)
        deadline = time.monotonic() + self.settings.task_timeout
        failures = 0
        while time.monotonic() < deadline:
            try:
                remote = await self._query(job, key, attempt["provider_id"])
                failures = 0
            except ProviderError as exc:
                failures += 1
                if not exc.resumable or failures >= 5:
                    raise
                await asyncio.sleep(self.settings.poll_seconds)
                continue
            if remote.state == "failed":
                if getattr(remote, "cost", None) is not None:
                    attempt["cost"] = remote.cost
                raise ProviderError(remote.message)
            if remote.state == "complete":
                if getattr(remote, "cost", None) is not None:
                    attempt["cost"] = remote.cost
                target = self.store.directory(job["id"], job["kind"]) / f"{key}-v{attempt['number']}"
                attempt["output"] = await self.provider.download(key, remote.url, target)
                attempt.update(state="complete", finished_at=now(), error=None, resumable=False)
                selected.update(state="complete", current=attempt["number"], stale=False)
                if key in job.get("pending_stages", []):
                    job["pending_stages"].remove(key)
                self.store.save(job)
                self.invalidate_quota_cache()
                return
            await asyncio.sleep(self.settings.poll_seconds)
        raise ProviderError("查询已到本机等待时限；重试将继续查询当前任务，不会重新付费生成", True)
