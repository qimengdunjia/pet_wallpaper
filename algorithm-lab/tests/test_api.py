"""文件用途：验证上传与视频设置、文件白名单、Range 播放、同源校验和无密钥行为。"""

import asyncio
import json
import shutil
import subprocess
import time
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.billing import extract_task_cost
from app.config import Settings
from app.kling import RemoteTask
from app.main import create_app
from app.storage import normalize_photo
from tests.test_workflow import FakeProvider, photo


def completed(client, job_id):
    """等待本地替身完成；参数为客户端和任务 ID，返回最终公开状态。"""
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] == "complete":
            return job
        time.sleep(.01)
    raise AssertionError(job)


def test_image_versions_feed_video_with_exact_local_frame(tmp_path):
    """覆盖独立出图、历史素材选择、视频快照、文件访问与输入校验。"""
    provider = FakeProvider()
    app = create_app(Settings(api_key="test-only", data_dir=tmp_path, poll_seconds=.001), provider)
    with TestClient(app) as client:
        for page in ("/", "/image-to-image", "/image-to-video", "/assets/app.js"):
            assert client.get(page).status_code == 200
        assert "test-only" not in client.get("/api/config").text
        assert client.get("/api/config").json()["default_video_options"] == {
            "model": "kling-3.0", "duration": 4, "resolution": "720p", "frame_mode": "first_last",
        }
        files = {"file": ("pet.jpg", photo(), "image/jpeg")}
        options = {"model": "kling-image-o1", "resolution": "1k", "aspect_ratio": "9:16"}
        for invalid in ({"model": "unknown"}, {"resolution": "4k"}, {"aspect_ratio": "32:9"}):
            data = {"image_options": json.dumps(options | invalid)}
            assert client.post("/api/image-jobs", files=files, data=data).status_code == 422
        assert provider.submitted == []
        response = client.post("/api/image-jobs", files=files, data={"prompt": "保留花纹", "image_options": json.dumps(options)})
        assert response.status_code == 202
        image = completed(client, response.json()["id"])
        image_id = image["id"]
        assert image["image_prompt"] == "保留花纹"
        assert image["reference_urls"] == [image["input_url"]]
        assert image["image_options"] == options
        assert list(image["stages"]) == ["idle"]
        assert provider.submitted == ["idle"]
        assert (tmp_path / "images" / image_id / "original.jpg").is_file()
        image_v1 = image["stages"]["idle"]["url"]
        assert "attachment" in client.get(image_v1 + "?download=true").headers["content-disposition"]
        assert client.get(f"/api/jobs/{image_id}/files/job.json").status_code == 404

        assert client.post(f"/api/jobs/{image_id}/retry", json={"stage": "idle"}).status_code == 202
        assert completed(client, image_id)["stages"]["idle"]["version"] == 2
        assert provider.image_options.model_dump() == options
        gallery = client.get("/api/idle-images").json()["images"]
        assert [item["version"] for item in gallery] == [2, 1]
        assert gallery[1]["url"] == image_v1

        source = {"source_job_id": image_id, "source_version": "1", "prompt": "缓慢眨眼"}
        assert client.post("/api/video-jobs", data=source, files=files).status_code == 422
        assert client.post("/api/video-jobs", data=source | {"source_version": "99"}).status_code == 404
        options = {"model": "kling-4.0-flash", "duration": 3, "resolution": "720p", "frame_mode": "first"}
        for invalid in ({"duration": 21}, {"duration": 3.5}, {"resolution": "1080p"}, {"frame_mode": "first_last"}):
            data = source | {"video_options": json.dumps(options | invalid)}
            assert client.post("/api/video-jobs", data=data).status_code == 422

        response = client.post("/api/video-jobs", data=source | {"video_options": json.dumps(options)})
        assert response.status_code == 202
        video = completed(client, response.json()["id"])
        assert video["idle_source"] == {"job_id": image_id, "version": 1}
        assert video["video_options"] == options
        assert provider.direct_video == ("缓慢眨眼", [client.get(image_v1).content])
        assert (tmp_path / "videos" / video["id"] / "first.jpg").read_bytes() == client.get(image_v1).content
        ranged = client.get(video["stages"]["video"]["url"], headers={"Range": "bytes=0-11"})
        assert ranged.status_code == 206 and len(ranged.content) == 12
        assert "remote_url" not in str(video)
        assert len(client.get("/api/jobs?kind=image").json()["jobs"]) == 1
        assert len(client.get("/api/jobs?kind=video").json()["jobs"]) == 1
        assert provider.submitted == ["idle", "idle", "video"]
        assert client.get("/api/jobs/not-an-id").status_code == 404

        assert client.delete(f"/api/idle-images/{image_id}/1").status_code == 200
        assert [item["version"] for item in client.get("/api/idle-images").json()["images"]] == [2]
        assert client.get(image_v1).status_code == 200
        assert client.post("/api/video-jobs", data=source).status_code == 404
        assert client.get(video["input_url"]).content == client.get(image_v1).content


def test_library_uploads_persist_and_video_keeps_frame_after_delete(tmp_path):
    """验证本地素材入库、重启恢复、首尾帧使用和删除后的任务快照。"""
    endpoint = "/api/idle-images"
    provider = FakeProvider()
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    original = photo()
    tail_image = BytesIO()
    Image.new("RGB", (320, 320), "navy").save(tail_image, "PNG")
    with TestClient(create_app(Settings(data_dir=tmp_path), provider)) as client:
        assert client.post(endpoint, files={"file": ("bad.png", b"bad")}).status_code == 422
        assert client.get(endpoint).json()["images"] == []
        first = client.post(endpoint, files={"file": ("首帧.jpg", original)})
        tail = client.post(endpoint, files={"file": ("尾帧.png", tail_image.getvalue())})
        assert first.status_code == tail.status_code == 201
        first, tail = first.json(), tail.json()
        assert first["name"] == "首帧.jpg"
        assert client.get(first["url"]).content == normalize_photo(original)
        assert client.get("/api/jobs").json()["jobs"] == []

    frames = {"prompt": "缓慢转头", "source_asset_id": first["asset_id"], "tail_source_asset_id": tail["asset_id"]}
    with TestClient(create_app(settings, provider)) as client:
        assert client.get(endpoint).json()["images"] == [tail, first]
        mixed = {"source_job_id": "0" * 32, "source_version": 1}
        assert client.post("/api/video-jobs", data=frames | mixed).status_code == 422
        response = client.post("/api/video-jobs", data=frames)
        assert response.status_code == 202
        job = completed(client, response.json()["id"])
        assert job["idle_source"] == {"asset_id": first["asset_id"]}
        assert job["tail_source"] == {"asset_id": tail["asset_id"]}
        assert client.delete(tail["url"]).status_code == 200
        assert client.get(tail["url"]).status_code == 404
        assert client.get(endpoint).json()["images"] == [first]
        assert client.post("/api/video-jobs", data=frames).status_code == 404
        assert client.post(f"/api/jobs/{job['id']}/retry", json={"stage": "video"}).status_code == 202
        redone = completed(client, job["id"])
        assert redone["stages"]["video"]["version"] == 2
        assert provider.direct_video[1] == [normalize_photo(original), normalize_photo(tail_image.getvalue())]

    with TestClient(create_app(settings, provider)) as client:
        assert client.get(endpoint).json()["images"] == [first]


def test_no_credentials_and_bad_uploads(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path / "no-key"), FakeProvider())) as client:
        assert client.get("/api/config").json()["configured"] is False
        assert client.post("/api/image-jobs", files={"file": ("pet.jpg", photo())}).status_code == 503
    with TestClient(create_app(Settings(api_key="test-only", data_dir=tmp_path / "with-key"), FakeProvider())) as client:
        assert client.post("/api/image-jobs", files={"file": ("fake.jpg", b"not a picture")}).status_code == 422
        assert client.post("/api/image-jobs", headers={"Content-Length": str(102 * 1024 * 1024)}).status_code == 413
        assert client.post("/api/image-jobs", headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/", headers={"Host": "evil.example"}).status_code == 400


def test_prd_presets_preserve_the_shared_transition_frame(tmp_path):
    """验证预设参数、过场关键帧原样复用，以及入场和等待段引用同一版本。"""
    provider = FakeProvider()
    settings = Settings(api_key="test-only", data_dir=tmp_path, poll_seconds=.001)
    photos = [("file", (name, photo(), "image/jpeg")) for name in ("cat.jpg", "dog.jpg")]
    with TestClient(create_app(settings, provider)) as client:
        config = client.get("/api/config").json()
        assert [len(group) for group in config["video_presets"].values()] == [3, 3, 4]
        assert client.post("/api/image-jobs", files=photos, data={"preset": "dog-idle"}).status_code == 422
        assert client.post("/api/image-jobs", files=photos[:1], data={"preset": "chase-entry"}).status_code == 422
        entry = client.post("/api/image-jobs", files=photos, data={"preset": "chase-entry"}).json()
        completed(client, entry["id"])
        pair = client.post("/api/image-jobs", files=photos, data={"preset": "chase-pair"}).json()
        pair = completed(client, pair["id"])
        pair_url = pair["stages"]["idle"]["url"]
        pair_path = tmp_path / "images" / pair["id"] / pair_url.rsplit("/", 1)[1]
        Image.new("RGB", (640, 360), "green").save(pair_path, "JPEG")
        gallery = client.get("/api/idle-images").json()["images"]
        assert [image["preset"] for image in gallery] == ["chase-pair", "chase-entry"]

        intro = {"preset": "chase-intro", "source_job_id": entry["id"], "source_version": 1}
        assert client.post("/api/video-jobs", data=intro).status_code == 422
        tail = {"tail_source_job_id": pair["id"], "tail_source_version": 1}
        response = client.post("/api/video-jobs", data=intro | tail)
        assert response.status_code == 202
        intro_job = completed(client, response.json()["id"])
        assert intro_job["tail_source"] == {"job_id": pair["id"], "version": 1}
        assert intro_job["video_options"] == {
            "model": "kling-3.0", "duration": 3, "resolution": "720p", "frame_mode": "first_last",
        }
        assert intro_job["video_prompt"] == config["video_presets"]["追逐过场"]["chase-intro"]["prompt"]
        first_bytes, tail_bytes = provider.direct_video[1]
        assert first_bytes != tail_bytes == client.get(pair_url).content

        loop = {"preset": "chase-loop", "source_job_id": pair["id"], "source_version": 1}
        response = client.post("/api/video-jobs", data=loop)
        assert response.status_code == 202
        loop_job = completed(client, response.json()["id"])
        assert loop_job["preset"] == "chase-loop"
        assert loop_job["video_options"]["duration"] == 7
        assert loop_job["video_options"]["frame_mode"] == "first_last"
        assert client.get(intro_job["tail_url"]).content == client.get(loop_job["input_url"]).content


def test_prompt_presets_update_and_persist_across_restarts(tmp_path):
    """验证直接修改、另存名称、页面隔离及服务重启后的复用。"""
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    video_url = "/api/prompt-presets/video"
    image_url = "/api/prompt-presets/image"
    builtin_url = f"{video_url}/dog-center"
    changed = "狗狗向镜头探头，回到原位。"
    with TestClient(create_app(settings, FakeProvider())) as client:
        assert client.get(video_url).json() == {"presets": {}}
        assert client.put(builtin_url, json={"prompt": " "}).status_code == 422
        assert client.put(f"{video_url}/unknown", json={"prompt": changed}).status_code == 404
        assert client.put(builtin_url, json={"prompt": changed}).json()["prompt"] == changed
        body = {"name": "小狗探头", "prompt": changed, "base_preset": "dog-center"}
        response = client.post(video_url, json=body)
        assert response.status_code == 201
        copied = response.json()
        custom_url = f"{video_url}/{copied['id']}"
        assert client.post(video_url, json=body).status_code == 409
        assert client.post(image_url, json=body).status_code == 422
        revised_copy = "先抬起头，再回到原位。"
        assert client.put(custom_url, json={"prompt": revised_copy}).json() == copied | {"prompt": revised_copy}

    provider = FakeProvider()
    with TestClient(create_app(settings, provider)) as client:
        prompts = client.get(video_url).json()["presets"]
        assert prompts["dog-center"]["prompt"] == changed
        assert prompts[copied["id"]]["prompt"] == revised_copy
        assert client.get(image_url).json() == {"presets": {}}
        response = client.post("/api/video-jobs", files={"file": ("dog.jpg", photo())}, data={"preset": "dog-center"})
        assert response.status_code == 202
        job = completed(client, response.json()["id"])
        assert job["video_prompt"] == changed
        assert job["video_options"] == {
            "model": "kling-3.0", "duration": 4, "resolution": "720p", "frame_mode": "first_last",
        }


@pytest.mark.skipif(not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe")), reason="需要本机 FFmpeg")
def test_video_info_measures_saved_mp4(tmp_path):
    """验证实测值来自登记的 MP4，且接口限制到该任务的已登记视频。"""
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    with TestClient(create_app(settings, FakeProvider())) as client:
        result = client.post("/api/video-jobs", files={"file": ("cat.jpg", photo())}, data={"preset": "cat-left"})
        job = completed(client, result.json()["id"])
        url = job["stages"]["video"]["url"].replace("/files/", "/video-info/")
        name = url.rsplit("/", 1)[1]
        path = tmp_path / "videos" / job["id"] / name
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=320x180:r=24:d=4",
            "-c:v", "mpeg4", str(path),
        ], check=True, timeout=10)
        assert client.get(url).json() == {
            "width": 320, "height": 180, "fps": 24, "duration": 4, "aspect_ratio": "16:9",
        }
        assert client.get(url.replace(name, "first.jpg")).status_code == 404
        assert client.get(url.replace(name, "other.mp4")).status_code == 404


def test_multiple_reference_images_preserve_order_on_redo(tmp_path):
    """验证多图逐张校验，并以原上传顺序保存、预览和重新提交。"""
    provider = FakeProvider()
    second = BytesIO()
    Image.new("RGB", (420, 420), "navy").save(second, "PNG")
    references = [("file", ("pet.jpg", photo())), ("file", ("scene.png", second.getvalue()))]
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    with TestClient(create_app(settings, provider)) as client:
        assert client.post("/api/image-jobs", files=[references[0]] * 11).status_code == 422
        assert client.post("/api/image-jobs", files=[references[0], ("file", ("bad.png", b"bad"))]).status_code == 422
        assert provider.submitted == []
        response = client.post("/api/image-jobs", files=references, data={"prompt": "使用<<<image_1>>>的宠物和<<<image_2>>>的背景"})
        assert response.status_code == 202
        job = completed(client, response.json()["id"])
        expected = [normalize_photo(photo()), normalize_photo(second.getvalue())]
        assert provider.image_references == expected
        assert [client.get(url).content for url in job["reference_urls"]] == expected
        assert client.post(f"/api/jobs/{job['id']}/retry", json={"stage": "idle"}).status_code == 202
        redo = completed(client, job["id"])
        assert redo["reference_urls"] == job["reference_urls"]
        assert redo["stages"]["idle"]["version"] == 2 and provider.image_references == expected


def test_batch_generates_each_photo_concurrently_and_isolates_failure(tmp_path):
    """通过阻塞查询验证任务实际重叠运行、等待空位以及单张失败后继续生成。"""

    class BatchProvider(FakeProvider):
        """暂挂首批远端查询并让其中第二张失败。"""

        def __init__(self):
            super().__init__()
            self.release = asyncio.Event()
            self.inputs = []

        async def submit(self, stage, references, external_id, **options):
            """记录每次请求的单张输入并返回模拟任务 ID。"""
            self.inputs.append([reference.read_bytes() for reference in references])
            return await super().submit(stage, references, external_id, **options)

        async def query(self, stage, task_id, *, image_model=None):
            """等测试核对并发后返回远端状态。"""
            await self.release.wait()
            if task_id == "2":
                return RemoteTask("failed", message="模拟单图失败")
            return await super().query(stage, task_id, image_model=image_model)

    provider = BatchProvider()
    files = []
    expected = []
    for index, color in enumerate(("red", "green", "blue", "yellow")):
        image = BytesIO()
        Image.new("RGB", (320, 320), color).save(image, "JPEG")
        files.append(("file", (f"pet-{index}.jpg", image.getvalue())))
        expected.append([normalize_photo(image.getvalue())])
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    with TestClient(create_app(settings, provider)) as client:
        image_options = {"model": "kling-v3", "resolution": "1k", "aspect_ratio": "9:16"}
        data = {"image_options": json.dumps(image_options)}
        assert client.post("/api/image-jobs", files=files[:2], data=data).status_code == 422
        for invalid in ({"resolution": "4k"}, {"aspect_ratio": "auto"}):
            data_invalid = {"image_options": json.dumps(image_options | invalid)}
            assert client.post("/api/image-batches", files=files[:1], data=data_invalid).status_code == 422
        response = client.post("/api/image-batches", files=files, data=data)
        assert response.status_code == 202
        created = response.json()["jobs"]
        path = f"/api/image-batches/{created[0]['batch_id']}"
        for _ in range(100):
            jobs = client.get(path).json()["jobs"]
            if all(job["stages"]["idle"]["attempt"] for job in jobs[:3]):
                break
            time.sleep(.01)
        assert [job["batch_index"] for job in jobs] == [1, 2, 3, 4]
        assert [job["status"] for job in jobs] == ["running", "running", "running", "queued"]
        assert provider.inputs == expected[:3]
        client.portal.call(provider.release.set)
        for _ in range(100):
            jobs = client.get(path).json()["jobs"]
            if not client.get("/api/config").json()["busy"]:
                break
            time.sleep(.01)
        jobs = client.get(path).json()["jobs"]
        assert [job["status"] for job in jobs] == ["complete", "failed", "complete", "complete"]
        assert provider.inputs == expected
        assert all(job["image_options"] == image_options for job in jobs)
        assert len(client.get("/api/idle-images").json()["images"]) == 3
        assert client.post(f"/api/jobs/{jobs[1]['id']}/retry", json={"stage": "idle"}).status_code == 202
        assert completed(client, jobs[1]["id"])["batch_index"] == 2
        assert provider.inputs == [*expected, expected[1]]
        assert provider.image_query_model == "kling-v3"


def test_batch_reuses_one_style_reference_per_subject(tmp_path):
    """验证每个任务使用自己的主体图和同一张风格图，重做继续使用该组合。"""
    provider = FakeProvider()
    subjects = [photo()]
    for color in ("navy", "gray"):
        image = BytesIO()
        Image.new("RGB", (420, 420), color).save(image, "PNG")
        subjects.append(image.getvalue())
    files = [("file", ("subject.jpg", subjects[0])), ("file", ("subject.png", subjects[1]))]
    style = ("style", ("style.png", subjects[2]))
    settings = Settings(api_key="test-only", data_dir=tmp_path)
    with TestClient(create_app(settings, provider)) as client:
        standard = {"image_options": json.dumps({"model": "kling-v3"})}
        assert client.post("/api/image-batches", files=[*files, style], data=standard).status_code == 422
        assert client.post("/api/image-batches", files=[*files, style, style]).status_code == 422
        assert client.post("/api/image-batches", files=[*files, ("style", ("bad.png", b"bad"))]).status_code == 422
        assert provider.submitted == []
        response = client.post("/api/image-batches", files=[*files, style])
        assert response.status_code == 202
        created = response.json()["jobs"]
        for job, original in zip(created, subjects[:2]):
            result = completed(client, job["id"])
            assert "对 <<<image_1>>> 做局部编辑" in result["image_prompt"]
            assert "用 <<<image_2>>> 中的猫替换底图里的猫" in result["image_prompt"]
            assert "狮身人面" not in result["image_prompt"]
            assert result["reference_urls"] == [result["style_url"], result["input_url"]]
            assert [client.get(url).content for url in result["reference_urls"]] == [
                normalize_photo(subjects[2]), normalize_photo(original),
            ]
        assert provider.submitted == ["idle", "idle"]
        first = created[0]
        assert client.post(f"/api/jobs/{first['id']}/retry", json={"stage": "idle"}).status_code == 202
        assert completed(client, first["id"])["stages"]["idle"]["version"] == 2
        assert provider.image_references == [normalize_photo(subjects[2]), normalize_photo(subjects[0])]


def test_direct_video_uses_uploaded_frames_and_can_resume_download(tmp_path):
    """验证独立图生视频只提交视频任务，下载失败后沿用原远端任务。"""
    provider = FakeProvider()
    provider.download_failure = True
    tail = BytesIO()
    Image.new("RGB", (600, 400), "navy").save(tail, "PNG")
    files = {"file": ("first.jpg", photo()), "tail": ("tail.png", tail.getvalue())}
    options = {"model": "kling-3.0", "duration": 3, "resolution": "720p", "frame_mode": "first_last"}
    with TestClient(create_app(Settings(api_key="test-only", data_dir=tmp_path), provider)) as client:
        assert client.get("/image-to-video").status_code == 200
        response = client.post("/api/video-jobs", files=files, data={"prompt": "  "})
        assert response.status_code == 422
        response = client.post("/api/video-jobs", files=files, data={
            "prompt": "慢慢转头", "video_options": json.dumps(options | {"frame_mode": "first"}),
        })
        assert response.status_code == 422
        assert provider.submitted == []
        response = client.post("/api/video-jobs", files=files, data={
            "prompt": " 慢慢转头 ", "video_options": json.dumps(options),
        })
        assert response.status_code == 202
        job_path = f"/api/jobs/{response.json()['id']}"
        for status in ("failed", "complete"):
            if status == "complete":
                assert client.post(f"{job_path}/retry", json={"stage": "video"}).status_code == 202
            for _ in range(100):
                job = client.get(job_path).json()
                if job["status"] == status:
                    break
                time.sleep(.01)
            assert job["status"] == status
        assert job["kind"] == "video"
        assert list(job["stages"]) == ["video"]
        assert job["video_prompt"] == "慢慢转头"
        assert job["video_options"] == options
        assert provider.submitted == ["video"]
        assert provider.direct_video == (
            "慢慢转头", [client.get(job["input_url"]).content, client.get(job["tail_url"]).content],
        )
        assert provider.direct_video[1][0] != provider.direct_video[1][1]
        assert client.get("/api/jobs").json()["jobs"] == []
        assert client.get("/api/jobs?kind=video").json()["jobs"][0]["id"] == job["id"]
        assert client.post(f"{job_path}/retry", json={"stage": "idle"}).status_code == 409


def test_omni_video_saves_reference_images_for_redo_and_rejects_invalid_inputs(tmp_path):
    """验证 Omni 参考图的上传、回显、首帧复用、重做及模型和数量限制。"""
    provider = FakeProvider()
    options = {"model": "kling-3.0-omni", "duration": 3, "resolution": "720p", "frame_mode": "first_last"}
    reference = BytesIO()
    Image.new("RGB", (400, 400), "navy").save(reference, "PNG")
    files = [("file", ("first.jpg", photo())), ("reference", ("ref.png", reference.getvalue()))]
    with TestClient(create_app(Settings(api_key="test-only", data_dir=tmp_path), provider)) as client:
        invalid = options | {"model": "kling-3.0"}
        assert client.post("/api/video-jobs", files=files, data={"prompt": "眨眼", "video_options": json.dumps(invalid)}).status_code == 422
        many = [files[0], *([files[1]] * 6)]
        assert client.post("/api/video-jobs", files=many, data={"prompt": "眨眼", "video_options": json.dumps(options)}).status_code == 422
        response = client.post("/api/video-jobs", files=files, data={"prompt": "眨眼", "video_options": json.dumps(options)})
        assert response.status_code == 202
        job = completed(client, response.json()["id"])
        ref_url = job["video_reference_urls"][0]
        first = client.get(job["input_url"]).content
        ref = client.get(ref_url).content
        assert ref == normalize_photo(reference.getvalue())
        assert provider.direct_video[1] == [first, first, ref]
        assert client.post(f"/api/jobs/{job['id']}/retry", json={"stage": "video"}).status_code == 202
        job = completed(client, job["id"])
        assert job["stages"]["video"]["version"] == 2
        assert provider.direct_video[1] == [first, first, ref]
        assert provider.submitted == ["video", "video"]


def test_quota_endpoint_and_per_generation_costs(tmp_path):
    """验证剩余额度接口、无密钥降级以及每次图生图/图生视频的花费统计。"""
    with TestClient(create_app(Settings(data_dir=tmp_path / "no-key"), FakeProvider())) as client:
        quota = client.get("/api/account/quota").json()
        assert quota["configured"] is False
        assert quota["available"] is False
        assert quota["local_spend"]["total"] is None

    provider = FakeProvider()
    provider.packs = [{
        "id": "pack-1", "name": "可灵通用包", "type": "decreasing_total", "tier": "flagship",
        "applicable_models": "Kling 4.0 & Image 3.0", "category": "general",
        "total_quantity": 200.0, "remaining_quantity": 180.0,
        "total_text": "200", "remaining_text": "180", "status": "online",
    }]
    provider.cost_by_stage = {
        "idle": extract_task_cost({"final_unit_deduction": "8"}),
        "video": extract_task_cost({"billing": [
            {"charge_type": "unit", "amount": "4", "package_type": "video"},
            {"charge_type": "cash", "cash_type": "balance", "amount": "0.50", "currency": "CNY"},
        ]}),
    }
    with TestClient(create_app(Settings(api_key="test-only", data_dir=tmp_path / "with-key", poll_seconds=.001), provider)) as client:
        initial = client.get("/api/account/quota").json()
        assert initial["configured"] is True
        assert initial["available"] is True
        assert initial["online_packs"][0]["remaining_text"] == "180"

        img_resp = client.post("/api/image-jobs", files={"file": ("cat.jpg", photo())}, data={"prompt": "待机"})
        img_job = completed(client, img_resp.json()["id"])
        assert img_job["stages"]["idle"]["current_cost"]["label"] == "8 Units"
        assert img_job["stages"]["idle"]["total_cost"]["label"] == "8 Units"

        vid_resp = client.post("/api/video-jobs", files={"file": ("cat.jpg", photo())}, data={"prompt": "眨眼"})
        vid_job = completed(client, vid_resp.json()["id"])
        assert vid_job["stages"]["video"]["current_cost"]["label"] == "4 Units + ¥0.50"

        summary = client.get("/api/account/quota").json()["local_spend"]
        assert summary["image"]["label"] == "8 Units"
        assert summary["video"]["label"] == "4 Units + ¥0.50"
        assert summary["total"]["label"] == "12 Units + ¥0.50"
        assert summary["recorded_jobs"] == 2
