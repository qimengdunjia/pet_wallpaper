"""文件用途：用不计费的供应商替身验证单步生成和历史版本、失败重试和重启付费保护。"""

import asyncio
import io

import pytest
from PIL import Image

from app.billing import extract_task_cost
from app.config import Settings
from app.kling import ProviderError, RemoteTask, SubmissionUnknown
from app.service import JobConflict, JobService
from app.storage import normalize_photo


def photo() -> bytes:
    """创建内存测试图片；无参数，返回 JPEG 字节，不使用用户照片。"""
    output = io.BytesIO()
    Image.new("RGB", (600, 400), "#bcb89b").save(output, format="JPEG")
    return output.getvalue()


class FakeProvider:
    """离线供应商替身；可控制阻塞、远端失败、下载失败和提交结果不明。"""

    def __init__(self):
        self.submitted = []
        self.video_options = None
        self.image_options = None
        self.image_references = None
        self.image_query_model = None
        self.direct_video = None
        self.fail_stage = None
        self.download_failure = False
        self.unknown = False
        self.block = False
        self.queried = asyncio.Event()
        self.cost_by_stage = {}
        self.fail_cost = None
        self.packs = []
        self.quota_error = None
        self.quota_calls = 0

    async def close(self):
        """关闭测试替身；无参数，无返回值。"""

    async def account_costs(self, *, start_time=None, end_time=None):
        """返回模拟资源包余量；可配置异常或计数。"""
        self.quota_calls += 1
        if self.quota_error:
            raise ProviderError(self.quota_error, True)
        return self.packs

    async def submit(self, stage, references, external_id, *, video_options=None, video_prompt=None,
                     image_prompt=None, image_options=None):
        """记录模拟提交；参数同真实适配层，返回递增任务 ID 或模拟不明提交。"""
        self.submitted.append(stage)
        if self.unknown:
            raise SubmissionUnknown("模拟提交超时，需要核对")
        if stage == "video":
            self.direct_video = (video_prompt, [path.read_bytes() for path in references])
            self.video_options = video_options
        else:
            self.image_options = image_options
            self.image_references = [path.read_bytes() for path in references]
        return str(len(self.submitted))

    async def query(self, stage, task_id, *, image_model=None, video_model=None):
        """返回模拟任务状态；参数为阶段与 ID，返回统一状态，可控制阻塞。"""
        self.image_query_model = image_model
        self.queried.set()
        if self.block:
            await asyncio.Event().wait()
        if stage == self.fail_stage:
            self.fail_stage = None
            return RemoteTask("failed", message="模拟生成失败", cost=self.fail_cost)
        return RemoteTask("complete", f"https://cdn.example/{stage}-{task_id}", cost=self.cost_by_stage.get(stage))

    async def download(self, stage, url, target):
        """写入测试媒体；参数同真实下载，返回登记信息，绝不调用生成 API。"""
        if self.download_failure:
            self.download_failure = False
            raise ProviderError("模拟下载断网", True)
        path = target.with_suffix(".mp4" if stage == "video" else ".jpg")
        path.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 100 if stage == "video" else photo())
        return {"file": path.name, "mime": "video/mp4" if stage == "video" else "image/jpeg", "remote_url": url}


def make_service(tmp_path, provider=None):
    """创建隔离服务；参数为临时目录及可选替身，返回服务和替身。"""
    provider = provider or FakeProvider()
    settings = Settings(api_key="test-only", data_dir=tmp_path, poll_seconds=.001, task_timeout=1)
    return JobService(settings, provider), provider


def test_failed_image_can_retry(tmp_path):
    async def scenario():
        service, provider = make_service(tmp_path)
        provider.fail_stage = "idle"
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        assert service.store.load(job["id"])["active_stage"] == "idle"
        await service.retry(job["id"], "idle")
        await service.task
        assert provider.submitted == ["idle", "idle"]
        assert service.store.load(job["id"])["status"] == "complete"
        await service.close()
    asyncio.run(scenario())


def test_download_failure_reuses_provider_task(tmp_path):
    async def scenario():
        service, provider = make_service(tmp_path)
        provider.download_failure = True
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        assert service.store.load(job["id"])["status"] == "failed"
        await service.retry(job["id"], "idle")
        await service.task
        assert provider.submitted == ["idle"]
        assert len(service.store.load(job["id"])["stages"]["idle"]["attempts"]) == 1
        await service.close()
    asyncio.run(scenario())


def test_restart_resumes_known_task_and_rejects_overlap(tmp_path):
    async def scenario():
        provider = FakeProvider()
        provider.block = True
        service, _ = make_service(tmp_path, provider)
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await provider.queried.wait()
        with pytest.raises(JobConflict):
            await service.create(photo(), image_prompt="室内待机")
        with pytest.raises(JobConflict):
            await service.retry(job["id"], "idle")
        await service.close()
        provider.block = False
        recovered, _ = make_service(tmp_path, provider)
        await recovered.start()
        await recovered.task
        assert provider.submitted == ["idle"]
        assert recovered.store.load(job["id"])["status"] == "complete"
        await recovered.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("bind_existing", [True, False])
def test_unknown_submission_requires_manual_reconciliation(tmp_path, bind_existing):
    async def scenario():
        service, provider = make_service(tmp_path)
        provider.unknown = True
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        assert service.store.load(job["id"])["status"] == "needs_review"
        with pytest.raises(JobConflict):
            await service.retry(job["id"], "idle")
        await service.close()
        recovered, _ = make_service(tmp_path, provider)
        await recovered.start()
        assert not recovered.busy and len(provider.submitted) == 1
        provider.unknown = False
        await recovered.reconcile(job["id"], "idle", "existing" if bind_existing else None, not bind_existing)
        await recovered.task
        assert provider.submitted.count("idle") == (1 if bind_existing else 2)
        assert recovered.store.load(job["id"])["status"] == "complete"
        await recovered.close()
    asyncio.run(scenario())


def test_restart_during_submission_marks_review(tmp_path):
    async def scenario():
        service, provider = make_service(tmp_path)
        provider.unknown = True
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        saved = service.store.load(job["id"])
        saved["status"] = "running"
        saved["stages"]["idle"]["attempts"][-1]["state"] = "submitting"
        service.store.save(saved)
        await service.close()
        recovered, _ = make_service(tmp_path, provider)
        await recovered.start()
        assert recovered.store.load(job["id"])["status"] == "needs_review"
        assert len(provider.submitted) == 1 and not recovered.busy
        await recovered.close()
    asyncio.run(scenario())


def test_restart_after_result_saved_never_regenerates(tmp_path):
    async def scenario():
        service, provider = make_service(tmp_path)
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        saved = service.store.load(job["id"])
        saved.update(status="running", active_stage="idle", pending_stages=[])
        service.store.save(saved)
        await service.close()
        recovered, _ = make_service(tmp_path, provider)
        await recovered.start()
        await recovered.task
        assert provider.submitted == ["idle"]
        assert recovered.store.load(job["id"])["status"] == "complete"
        await recovered.close()
    asyncio.run(scenario())


def test_single_process_data_lock(tmp_path):
    async def scenario():
        first, _ = make_service(tmp_path)
        second, _ = make_service(tmp_path)
        await first.start()
        with pytest.raises(RuntimeError, match="单 worker"):
            await second.start()
        await first.close()
        await second.close()
    asyncio.run(scenario())


def test_repeated_query_failures_preserve_id_and_retry_without_submission(tmp_path):
    class QueryFailureProvider(FakeProvider):
        """模拟连续查询断网；恢复网络后仍返回原任务的结果。"""

        broken = True

        async def query(self, stage, task_id, *, image_model=None, video_model=None):
            """查询故障注入；参数为阶段和任务 ID，返回模拟状态或可恢复异常。"""
            if self.broken:
                raise ProviderError("模拟查询断网", True)
            return await super().query(stage, task_id, image_model=image_model)

    async def scenario():
        provider = QueryFailureProvider()
        service, _ = make_service(tmp_path, provider)
        await service.start()
        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        failed = service.store.load(job["id"])
        assert failed["status"] == "failed"
        assert failed["stages"]["idle"]["attempts"][-1]["provider_id"] == "1"
        provider.broken = False
        await service.retry(job["id"], "idle")
        await service.task
        assert provider.submitted == ["idle"]
        await service.close()
    asyncio.run(scenario())


def test_photo_validation_and_exif_removal():
    assert Image.open(io.BytesIO(normalize_photo(photo()))).format == "JPEG"
    for data in [b"not an image", b"<svg></svg>"]:
        with pytest.raises(ValueError):
            normalize_photo(data)
    output = io.BytesIO()
    Image.new("RGB", (200, 400)).save(output, format="PNG")
    with pytest.raises(ValueError, match="300"):
        normalize_photo(output.getvalue())
    output = io.BytesIO()
    image = Image.new("RGB", (600, 400))
    exif = Image.Exif()
    exif[270] = "private-test-metadata"
    exif[274] = 6
    image.save(output, format="JPEG", exif=exif)
    normalized = Image.open(io.BytesIO(normalize_photo(output.getvalue())))
    assert normalized.size == (400, 600) and not normalized.getexif()


def test_cost_persists_across_retries_and_quota_caching(tmp_path):
    """验证失败零扣费与成功多次重做花费累加，以及额度查询缓存与失效刷新。"""
    async def scenario():
        provider = FakeProvider()
        provider.fail_stage = "idle"
        provider.fail_cost = extract_task_cost({"final_unit_deduction": "0"})
        provider.cost_by_stage["idle"] = extract_task_cost({"final_unit_deduction": "8"})
        provider.packs = [{
            "id": "p1", "name": "图片包", "type": "decreasing_total", "tier": "general",
            "applicable_models": "Image 3.0 Omni", "category": "image",
            "total_quantity": 100.0, "remaining_quantity": 92.0,
            "total_text": "100", "remaining_text": "92", "status": "online",
        }]
        service, _ = make_service(tmp_path, provider)
        await service.start()

        first_quota = await service.get_quota()
        assert first_quota["available"] is True
        assert provider.quota_calls == 1
        second_quota = await service.get_quota()
        assert second_quota["cached"] is True
        assert provider.quota_calls == 1

        job = await service.create(photo(), image_prompt="室内待机")
        await service.task
        failed_public = service.store.public(service.store.load(job["id"]))
        assert failed_public["stages"]["idle"]["attempt"]["cost"]["label"] == "0（未扣费）"
        assert failed_public["stages"]["idle"]["current_cost"] is None

        await service.retry(job["id"], "idle")
        await service.task
        await service.retry(job["id"], "idle")
        await service.task
        done_public = service.store.public(service.store.load(job["id"]))
        assert done_public["stages"]["idle"]["current_cost"]["label"] == "8 Units"
        assert done_public["stages"]["idle"]["total_cost"]["label"] == "16 Units"

        # 任务完成后缓存被置为失效，并在超过节流窗口后重新请求远端。
        service._quota_last_attempt_at = 0.0
        after_quota = await service.get_quota()
        assert provider.quota_calls == 2
        assert after_quota["local_spend"]["total"]["label"] == "16 Units"
        assert after_quota["local_spend"]["today"]["label"] == "16 Units"
        assert after_quota["local_spend"]["recorded_jobs"] == 1

        provider.quota_error = "网络异常"
        service._quota_last_attempt_at = 0.0
        errored = await service.get_quota(force_refresh=True)
        assert errored["available"] is False
        assert errored["error"] == "网络异常"
        assert len(errored["online_packs"]) == 1
        assert errored["local_spend"]["total"]["label"] == "16 Units"
        await service.close()

    asyncio.run(scenario())
