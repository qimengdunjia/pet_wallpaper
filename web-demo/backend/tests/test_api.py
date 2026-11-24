"""文件用途：覆盖网页 Demo 设置认证、照片校验、幂等生成、媒体读取、任务恢复与可灵适配。"""

from __future__ import annotations

import base64
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from shutil import copyfile
from threading import Barrier

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = BACKEND_ROOT.parent / "assets"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app import main as demo_main  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import DemoDatabase  # noqa: E402
from app.main import create_app  # noqa: E402
from app.providers import BaseGenerationProvider, KlingGenerationProvider  # noqa: E402


def _make_jpeg_bytes(width: int = 640, height: int = 480, color: tuple[int, int, int] = (220, 140, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_settings(tmp_path: Path, **overrides) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        provider=overrides.get("provider", "mock"),
        data_dir=data_dir,
        assets_dir=ASSETS_DIR,
        frontend_dist=tmp_path / "no-dist",
        mock_delay_seconds=overrides.get("mock_delay_seconds", 0.06),
        mock_controls_enabled=overrides.get("mock_controls_enabled", True),
        settings_password=overrides.get("settings_password", ""),
        kling_api_key=overrides.get("kling_api_key", ""),
        kling_base_url=overrides.get("kling_base_url", "https://api-beijing.klingai.com"),
        kling_poll_seconds=overrides.get("kling_poll_seconds", 0.01),
        kling_task_timeout=overrides.get("kling_task_timeout", 30.0),
        disable_worker_lock=True,
    )


def _wait_job(client: TestClient, job_id: str, headers: dict | None = None, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/api/generations/{job_id}", headers=headers or {})
        assert resp.status_code == 200
        job = resp.json()["job"]
        if job["status"] in {"ready", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"任务 {job_id} 在 {timeout}s 内未结束")


def test_settings_require_password_and_survive_restart(tmp_path: Path):
    settings = _make_settings(tmp_path, settings_password="设置验收口令")
    login = {"password": "设置验收口令"}
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/settings/unlock", json={"password": "错误密码"}).status_code == 401
        unlocked = client.post("/api/settings/unlock", json=login).json()
        generation = unlocked["settings"]
        assert (generation["image_width"], generation["image_height"]) == (2560, 1440)
        assert (generation["video_width"], generation["video_height"]) == (1920, 1080)
        for species in ("cat", "dog"):
            assert set(generation["prompts"][species]) == {"image", "idle", "left", "center", "right"}

        generation["provider"] = "comfyui"
        generation["prompts"]["cat"]["idle"] = "轻轻呼吸，首尾保持同一姿势。"
        generation["prompts"]["dog"]["right"] = "用鼻尖碰触右侧热区。"
        assert client.put("/api/settings", json=generation).status_code == 401
        auth = {"Authorization": f"Bearer {unlocked['token']}"}
        invalid = {**generation, "video_height": 1081}
        assert client.put("/api/settings", headers=auth, json=invalid).status_code == 422
        assert client.put("/api/settings", headers=auth, json=generation).status_code == 200
        assert client.get("/api/config").json()["provider"] == "comfyui"

    with TestClient(create_app(settings)) as client:
        assert client.put("/api/settings", headers=auth, json=generation).status_code == 401
        assert client.post("/api/settings/unlock", json=login).json()["settings"] == generation


def test_pet_crud_and_photo_validation(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-crud"}
    with TestClient(create_app(settings)) as client:
        cfg = client.get("/api/config").json()
        assert cfg["provider"] == "mock"
        assert cfg["transitions"]["intro"]["duration"] == 3.0
        assert cfg["transitions"]["loop"]["duration"] == 7.0

        # 创建并更新宠物信息
        res = client.post(
            "/api/pets",
            json={"species": "cat", "name": "橘宝", "gender": "弟弟", "breed": "橘猫"},
            headers=headers,
        )
        assert res.status_code == 201
        pet_id = res.json()["pet"]["id"]

        patch = client.patch(
            f"/api/pets/{pet_id}",
            json={"name": "大橘", "gender": "妹妹", "breed": "英短橘"},
            headers=headers,
        )
        assert patch.status_code == 200
        assert patch.json()["pet"]["name"] == "大橘"
        assert patch.json()["pet"]["gender"] == "妹妹"
        assert patch.json()["pet"]["breed"] == "英短橘"

        # 拒绝非图片、过小图片与无历史照片空提交
        bad_bytes = client.post(
            "/api/generations",
            data={"pet_id": pet_id, "idempotency_key": "bad-1"},
            files={"photo": ("bad.jpg", b"not-an-image", "image/jpeg")},
            headers=headers,
        )
        assert bad_bytes.status_code == 422

        tiny_img = _make_jpeg_bytes(200, 200)
        too_small = client.post(
            "/api/generations",
            data={"pet_id": pet_id, "idempotency_key": "bad-2"},
            files={"photo": ("tiny.jpg", tiny_img, "image/jpeg")},
            headers=headers,
        )
        assert too_small.status_code == 422

        no_photo = client.post(
            "/api/generations",
            data={"pet_id": pet_id, "idempotency_key": "bad-3"},
            headers=headers,
        )
        assert no_photo.status_code == 422


def test_idempotent_generation_asset_manifest_and_range_requests(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-gen"}
    with TestClient(create_app(settings)) as client:
        cat_id = client.post("/api/pets", json={"species": "cat", "name": "米粒"}, headers=headers).json()["pet"]["id"]
        dog_id = client.post("/api/pets", json={"species": "dog", "name": "豆包"}, headers=headers).json()["pet"]["id"]
        photo = _make_jpeg_bytes(640, 480)

        first = client.post(
            "/api/generations",
            data={"pet_id": cat_id, "idempotency_key": "idem-cat-1"},
            files={"photo": ("cat.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert first.status_code == 202
        first_body = first.json()
        assert first_body["reused"] is False
        assert first_body["pet"]["original_photo_url"] == f"/api/media/pets/{cat_id}/original?session=sess-gen"
        job_id = first_body["job"]["id"]

        # 同幂等键重复提交返回原任务
        dup = client.post(
            "/api/generations",
            data={"pet_id": cat_id, "idempotency_key": "idem-cat-1"},
            files={"photo": ("cat.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert dup.status_code == 200
        assert dup.json()["reused"] is True
        assert dup.json()["job"]["id"] == job_id

        # 其他宠物复用同一幂等键被拒绝
        conflict = client.post(
            "/api/generations",
            data={"pet_id": dog_id, "idempotency_key": "idem-cat-1"},
            files={"photo": ("dog.jpg", photo, "image/jpeg")},
            headers=headers,
        )
        assert conflict.status_code == 409

        done = _wait_job(client, job_id, headers)
        assert done["status"] == "ready"
        assets = done["assets"]
        assert assets["idle_image"]["width"] == 1920
        assert assets["idle_image"]["height"] == 1080
        for slot in ("left", "center", "right"):
            meta = assets["actions"][slot]
            assert meta["format"] == "mp4"
            assert meta["width"] == 1920
            assert meta["height"] == 1080
            assert meta["fps"] == 24.0
            assert meta["duration"] > 3.5

        # 验证原图与待机图无需自定义 Header 也可通过带 session 查询参数的 URL 正常访问（供 <img>/<video> 使用）
        idle_url = assets["idle_image"]["url"]
        assert "session=sess-gen" in idle_url
        idle_resp = client.get(idle_url)
        assert idle_resp.status_code == 200
        # 跨会话且无权访问仍被拦截
        cross_resp = client.get(idle_url.split("?")[0], headers={"X-Demo-Session": "other-sess"})
        assert cross_resp.status_code == 404

        orig_resp = client.get(f"/api/media/pets/{cat_id}/original", headers=headers)
        assert orig_resp.status_code == 200
        assert orig_resp.content[:2] == b"\xff\xd8"

        video_url = assets["actions"]["center"]["url"]
        range_resp = client.get(video_url, headers={**headers, "Range": "bytes=0-1023"})
        assert range_resp.status_code == 206
        assert range_resp.headers["content-range"].startswith("bytes 0-1023/")
        assert len(range_resp.content) == 1024

        trans_range = client.get("/api/assets/transitions/chase-loop-7s.mp4", headers={"Range": "bytes=0-511"})
        assert trans_range.status_code == 206
        assert len(trans_range.content) == 512


@pytest.mark.parametrize("same_pet", [True, False])
def test_concurrent_generation_key_conflicts_keep_one_job_and_photo(tmp_path: Path, monkeypatch, same_pet: bool):
    """让两次上传同时通过前置幂等检查，验证重放和跨档案冲突均只保留一份。"""
    settings = _make_settings(tmp_path)
    barrier = Barrier(2, timeout=5)
    normalize_photo = demo_main.normalize_photo

    def normalize_together(content: bytes) -> bytes:
        normalized = normalize_photo(content)
        barrier.wait()
        return normalized

    monkeypatch.setattr(demo_main, "normalize_photo", normalize_together)
    photo = _make_jpeg_bytes()
    with TestClient(create_app(settings)) as client:
        cat = client.post("/api/pets", json={"species": "cat"}).json()["pet"]
        dog = client.post("/api/pets", json={"species": "dog"}).json()["pet"]

        def submit(pet_id: str) -> httpx.Response:
            return client.post(
                "/api/generations",
                data={"pet_id": pet_id, "idempotency_key": "concurrent-key"},
                files={"photo": ("pet.jpg", photo, "image/jpeg")},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            replies = list(executor.map(submit, [cat["id"], cat["id"] if same_pet else dog["id"]]))

        expected = [200, 202] if same_pet else [202, 409]
        assert sorted(reply.status_code for reply in replies) == expected
        jobs = client.get("/api/generations").json()["jobs"]
        assert len(jobs) == 1
        if same_pet:
            assert {reply.json()["job"]["id"] for reply in replies} == {jobs[0]["id"]}
        assert len(list((settings.data_dir / "uploads").glob("*/*.jpg"))) == 1


def test_failure_and_corrupt_bundle_preserve_existing_wallpaper(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-fail"}
    with TestClient(create_app(settings)) as client:
        cat = client.post("/api/pets", json={"species": "cat", "name": "奶糖"}, headers=headers).json()["pet"]
        cat_id = cat["id"]
        job1 = client.post(
            "/api/generations",
            data={"pet_id": cat_id, "idempotency_key": "ok-1"},
            files={"photo": ("cat.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]
        done1 = _wait_job(client, job1["id"], headers)
        assert done1["status"] == "ready"
        ver1_id = done1["version_id"]

        put_res = client.put(
            "/api/current-wallpaper",
            json={"pet_id": cat_id, "version_id": ver1_id},
            headers=headers,
        )
        assert put_res.status_code == 200

        # 再次提交并注入失败，验证不影响既有版本和当前壁纸
        job2 = client.post(
            "/api/generations",
            data={
                "pet_id": cat_id,
                "idempotency_key": "fail-2",
                "mock_fail": "true",
                "mock_fail_stage": "center",
                "mock_fail_message": "中区动作生成超时",
            },
            headers=headers,
        ).json()["job"]
        failed = _wait_job(client, job2["id"], headers)
        assert failed["status"] == "failed"
        assert "中区动作生成超时" in failed["error_message"]

        pets = client.get("/api/pets", headers=headers).json()["pets"]
        assert pets[0]["active_version_id"] == ver1_id
        current = client.get("/api/current-wallpaper", headers=headers).json()["current"]
        assert current["version_id"] == ver1_id

    # 验证残缺视频会被校验层拒绝发布
    class CorruptProvider(BaseGenerationProvider):
        async def generate(self, job, pet, output_dir, persist_remote, update_progress):
            output_dir.mkdir(parents=True, exist_ok=True)
            idle = output_dir / "idle.jpg"
            idle.write_bytes(_make_jpeg_bytes(1920, 1080))
            bad = output_dir / "left.mp4"
            bad.write_bytes(b"corrupt-mp4-data")
            return idle, {"left": bad, "center": bad, "right": bad}

    settings2 = _make_settings(tmp_path / "corrupt")
    with TestClient(create_app(settings2, provider=CorruptProvider())) as client:
        pet_id = client.post("/api/pets", json={"species": "dog"}, headers=headers).json()["pet"]["id"]
        job = client.post(
            "/api/generations",
            data={"pet_id": pet_id, "idempotency_key": "corrupt-1"},
            files={"photo": ("dog.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]
        res = _wait_job(client, job["id"], headers)
        assert res["status"] == "failed"
        assert res["version_id"] is None


def test_wallpaper_switch_and_process_restart_recovery(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-restart"}

    # 第一轮运行：生成猫和狗，保存当前壁纸为狗
    with TestClient(create_app(settings)) as client:
        cat_id = client.post("/api/pets", json={"species": "cat", "name": "汤圆"}, headers=headers).json()["pet"]["id"]
        dog_id = client.post("/api/pets", json={"species": "dog", "name": "旺财"}, headers=headers).json()["pet"]["id"]

        cat_job = client.post(
            "/api/generations",
            data={"pet_id": cat_id, "idempotency_key": "cat-1"},
            files={"photo": ("cat.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]["id"]
        dog_job = client.post(
            "/api/generations",
            data={"pet_id": dog_id, "idempotency_key": "dog-1"},
            files={"photo": ("dog.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]["id"]

        cat_done = _wait_job(client, cat_job, headers)
        dog_done = _wait_job(client, dog_job, headers)
        assert cat_done["status"] == "ready"
        assert dog_done["status"] == "ready"

        # 越权或错配 version_id 被拒绝
        mismatch = client.put(
            "/api/current-wallpaper",
            json={"pet_id": cat_id, "version_id": dog_done["version_id"]},
            headers=headers,
        )
        assert mismatch.status_code == 422

        saved = client.put(
            "/api/current-wallpaper",
            json={"pet_id": dog_id, "version_id": dog_done["version_id"]},
            headers=headers,
        )
        assert saved.status_code == 200

    # 模拟进程中断：直接向 SQLite 插入一只尚未完成的新猫任务（已完成 idle 阶段）
    db = DemoDatabase(settings.data_dir / "demo.sqlite3")
    cat2 = db.create_pet("sess-restart", "cat", "年糕")
    photo_rel = f"uploads/{cat2['id']}/orig.jpg"
    photo_abs = settings.data_dir / photo_rel
    photo_abs.parent.mkdir(parents=True, exist_ok=True)
    photo_abs.write_bytes(_make_jpeg_bytes())

    incomplete_job = db.create_generation_job(
        session_id="sess-restart",
        pet_id=cat2["id"],
        idempotency_key="recover-cat2",
        provider="mock",
        photo_path=photo_rel,
        mock_options={"delay_seconds": 0.06},
    )
    work_dir = settings.data_dir / "versions" / incomplete_job["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    copyfile(ASSETS_DIR / "samples" / "cat" / "idle.jpg", work_dir / "idle.jpg")
    db.update_job_progress(
        incomplete_job["id"],
        status="generating",
        stage="idle",
        progress=25,
        remote_tasks={"idle": {"state": "complete", "provider_id": "mock-pre"}},
    )
    db.close()

    # 第二轮重启进程：验证恢复上次壁纸，且未完成任务自动续跑直到 ready
    with TestClient(create_app(settings)) as client2:
        current = client2.get("/api/current-wallpaper", headers=headers).json()["current"]
        assert current["pet_id"] == dog_id
        assert current["pet"]["name"] == "旺财"

        recovered = _wait_job(client2, incomplete_job["id"], headers)
        assert recovered["status"] == "ready"
        assert recovered["assets"]["idle_image"]["width"] == 1920


def test_kling_provider_pipeline_and_resume(tmp_path: Path):
    import asyncio

    asyncio.run(_run_kling_provider_test(tmp_path))


async def _run_kling_provider_test(tmp_path: Path):
    sample_idle_bytes = (ASSETS_DIR / "samples" / "cat" / "idle.jpg").read_bytes()
    sample_video_bytes = (ASSETS_DIR / "samples" / "cat" / "left.mp4").read_bytes()
    photo_path = tmp_path / "photo.jpg"
    photo_path.write_bytes(_make_jpeg_bytes())

    submitted_video_frames: list[tuple[str, str]] = []
    post_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            post_paths.append(path)
            body = json.loads(request.content.decode("utf-8"))
            if path == "/v1/images/omni-image":
                return httpx.Response(200, json={"code": "0", "data": {"task_id": "img-task-1"}})
            if path == "/image-to-video/kling-3.0":
                contents = body["contents"]
                first = next(c["url"] for c in contents if c["type"] == "first_frame")
                last = next(c["url"] for c in contents if c["type"] == "last_frame")
                submitted_video_frames.append((first, last))
                idx = len(submitted_video_frames)
                return httpx.Response(200, json={"code": "0", "data": {"id": f"vid-task-{idx}"}})
        if request.method == "GET":
            if path == "/v1/images/omni-image/img-task-1":
                return httpx.Response(
                    200,
                    json={
                        "code": "0",
                        "data": {
                            "task_status": "succeed",
                            "task_result": {"images": [{"url": "https://cdn.example.com/idle.jpg"}]},
                        },
                    },
                )
            if path == "/tasks":
                tid = request.url.params["task_ids"]
                return httpx.Response(
                    200,
                    json={
                        "code": "0",
                        "data": [
                            {
                                "id": tid,
                                "status": "succeeded",
                                "outputs": [{"type": "video", "url": f"https://cdn.example.com/{tid}.mp4"}],
                            }
                        ],
                    },
                )
        return httpx.Response(404, json={"code": "404"})

    # 为内部下载客户端也提供受控 mock
    original_async_client = httpx.AsyncClient

    def fake_downloader(*args, **kwargs):
        def dl_handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith(".jpg"):
                return httpx.Response(200, content=sample_idle_bytes)
            return httpx.Response(200, content=sample_video_bytes)

        return original_async_client(transport=httpx.MockTransport(dl_handler))

    settings = _make_settings(tmp_path, provider="kling", kling_api_key="test-secret-key")
    api_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KlingGenerationProvider(settings, client=api_client)

    # Monkeypatch 下载阶段使用的 AsyncClient
    import app.providers as providers_mod

    old_client_cls = providers_mod.httpx.AsyncClient
    providers_mod.httpx.AsyncClient = fake_downloader  # type: ignore[misc]
    try:
        persisted_history: list[dict] = []

        async def persist_remote(remote: dict) -> None:
            persisted_history.append(json.loads(json.dumps(remote)))

        async def update_progress(_stage: str, _progress: int) -> None:
            return None

        out_dir = tmp_path / "out1"
        idle_path, action_paths = await provider.generate(
            {"id": "jobk1", "photo_path": str(photo_path), "remote_tasks": {}},
            {"species": "cat"},
            out_dir,
            persist_remote,
            update_progress,
        )
        assert idle_path.is_file()
        assert set(action_paths.keys()) == {"left", "center", "right"}
        assert len(submitted_video_frames) == 3
        expected_idle_b64 = base64.b64encode(sample_idle_bytes).decode("ascii")
        for first, last in submitted_video_frames:
            assert first == expected_idle_b64
            assert last == expected_idle_b64

        # 断点续跑测试：idle 已完成，left 已有 provider_id，不应重复 POST idle 和 left
        post_paths.clear()
        out_dir2 = tmp_path / "out2"
        out_dir2.mkdir(parents=True, exist_ok=True)
        (out_dir2 / "idle.jpg").write_bytes(sample_idle_bytes)
        await provider.generate(
            {
                "id": "jobk2",
                "photo_path": str(photo_path),
                "remote_tasks": {
                    "idle": {"state": "complete", "file": "idle.jpg"},
                    "left": {"state": "running", "provider_id": "vid-resumed-left"},
                },
            },
            {"species": "cat"},
            out_dir2,
            persist_remote,
            update_progress,
        )
        # 仅新提交了 center 和 right 两次 POST
        assert post_paths == ["/image-to-video/kling-3.0", "/image-to-video/kling-3.0"]
    finally:
        providers_mod.httpx.AsyncClient = old_client_cls  # type: ignore[misc]
        await api_client.aclose()


def test_default_wallpaper_config_assets_and_switch_back(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-default-wp"}
    with TestClient(create_app(settings)) as client:
        cfg = client.get("/api/config", headers=headers).json()
        dw = cfg["default_wallpaper"]
        assert dw is not None
        assert dw["pet_id"] == "default-dog"
        assert dw["version_id"] == "default-dog-v1"
        assert dw["pet"]["is_default"] is True
        assert dw["pet"]["species"] == "dog"
        assert dw["assets"]["idle_video"]["width"] == 1920
        assert dw["assets"]["idle_video"]["height"] == 1080
        assert dw["assets"]["idle_video"]["fps"] == 24.0
        for slot in ("left", "center", "right"):
            action = dw["assets"]["actions"][slot]
            assert action["width"] == 1920
            assert action["height"] == 1080
            assert action["fps"] == 24.0

        # 验证默认壁纸静态首帧及视频槽位可正常读取与 Range 分段请求
        idle_img_resp = client.get(dw["assets"]["idle_image"]["url"])
        assert idle_img_resp.status_code == 200
        idle_meta = dw["assets"]["idle_image"]
        with Image.open(io.BytesIO(idle_img_resp.content)) as idle_image:
            assert idle_image.size == (idle_meta["width"], idle_meta["height"])
            assert Image.MIME[idle_image.format] == idle_meta["mime"] == idle_img_resp.headers["content-type"]

        for video_url in (
            dw["assets"]["idle_video"]["url"],
            dw["assets"]["actions"]["left"]["url"],
            dw["assets"]["actions"]["center"]["url"],
            dw["assets"]["actions"]["right"]["url"],
        ):
            range_resp = client.get(video_url, headers={"Range": "bytes=0-511"})
            assert range_resp.status_code == 206
            assert len(range_resp.content) == 512

        # 生成并保存一个自定义宠物壁纸后，验证可切回默认狗狗壁纸
        cat_id = client.post("/api/pets", json={"species": "cat", "name": "咪咪"}, headers=headers).json()["pet"]["id"]
        job_id = client.post(
            "/api/generations",
            data={"pet_id": cat_id, "idempotency_key": "default-back-1"},
            files={"photo": ("cat.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]["id"]
        done = _wait_job(client, job_id, headers)
        assert done["status"] == "ready"
        assert client.put(
            "/api/current-wallpaper",
            json={"pet_id": cat_id, "version_id": done["version_id"]},
            headers=headers,
        ).status_code == 200

        bad_switch = client.put(
            "/api/current-wallpaper",
            json={"pet_id": "default-dog", "version_id": "invalid-ver"},
            headers=headers,
        )
        assert bad_switch.status_code == 422

        switch_back = client.put(
            "/api/current-wallpaper",
            json={"pet_id": "default-dog", "version_id": "default-dog-v1"},
            headers=headers,
        )
        assert switch_back.status_code == 200
        assert switch_back.json()["current"]["pet_id"] == "default-dog"
        assert client.get("/api/current-wallpaper", headers=headers).json()["current"] is None


def test_delete_pet_cascades_files_current_wallpaper_and_cancels_jobs(tmp_path: Path):
    settings = _make_settings(tmp_path)
    headers = {"X-Demo-Session": "sess-delete"}
    with TestClient(create_app(settings)) as client:
        assert client.delete("/api/pets/default-dog", headers=headers).status_code == 400
        assert client.delete("/api/pets/missing-pet", headers=headers).status_code == 404

        pet_id = client.post(
            "/api/pets",
            json={"species": "dog", "name": "豆包", "gender": "弟弟", "breed": "柯基"},
            headers=headers,
        ).json()["pet"]["id"]
        job_id = client.post(
            "/api/generations",
            data={"pet_id": pet_id, "idempotency_key": "del-ready-1"},
            files={"photo": ("dog.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]["id"]
        done = _wait_job(client, job_id, headers)
        assert done["status"] == "ready"
        assert client.put(
            "/api/current-wallpaper",
            json={"pet_id": pet_id, "version_id": done["version_id"]},
            headers=headers,
        ).status_code == 200

        upload_dir = settings.data_dir / "uploads" / pet_id
        version_dir = settings.data_dir / "versions" / job_id
        assert upload_dir.is_dir()
        assert version_dir.is_dir()

        deleted = client.delete(f"/api/pets/{pet_id}", headers=headers)
        assert deleted.status_code == 200
        assert deleted.json() == {"deleted_pet_id": pet_id, "was_current": True}

        assert client.get("/api/pets", headers=headers).json()["pets"] == []
        assert client.get(f"/api/generations/{job_id}", headers=headers).status_code == 404
        assert client.get("/api/current-wallpaper", headers=headers).json()["current"] is None
        assert not upload_dir.exists()
        assert not version_dir.exists()

        # 删除正在生成的宠物时应取消后台任务并清理目录
        slow_pet_id = client.post(
            "/api/pets",
            json={"species": "cat", "name": "奶糖"},
            headers=headers,
        ).json()["pet"]["id"]
        slow_job_id = client.post(
            "/api/generations",
            data={"pet_id": slow_pet_id, "idempotency_key": "del-slow-1", "mock_delay_seconds": "4.0"},
            files={"photo": ("cat.jpg", _make_jpeg_bytes(), "image/jpeg")},
            headers=headers,
        ).json()["job"]["id"]
        time.sleep(0.08)

        slow_deleted = client.delete(f"/api/pets/{slow_pet_id}", headers=headers)
        assert slow_deleted.status_code == 200
        assert slow_deleted.json() == {"deleted_pet_id": slow_pet_id, "was_current": False}
        assert not (settings.data_dir / "uploads" / slow_pet_id).exists()
        assert not (settings.data_dir / "versions" / slow_job_id).exists()
