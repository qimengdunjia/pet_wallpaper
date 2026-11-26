"""文件用途：验证 ComfyUI 双卡视频并行、既有任务恢复和第二实例离线回退。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from app.comfyui import ComfyUIGenerationProvider
from app.comfyui_workflows import OUTPUT_NODE
from app.config import Settings

PRIMARY = "http://primary:8188"
SECONDARY = "http://secondary:8189"


def test_confirmed_decoration_uses_original_photo_for_idle_and_idle_for_all_videos(tmp_path):
    """断言装扮任务的正面照不会被作为待机图的输入，视频统一引用最终待机图。"""
    photo = tmp_path / "original.jpg"
    photo.write_bytes(b"user-original-photo")
    assets_dir = Path(__file__).resolve().parents[2] / "assets"

    async def run():
        submissions = {}

        async def handle(request):
            path = request.url.path
            if path == "/upload/image":
                if b"user-original-photo" in request.content:
                    return httpx.Response(200, json={"name": "original.jpg"})
                assert b"bow-tie.webp" in request.content
                return httpx.Response(200, json={"name": "bow-tie.webp"})
            if path == "/prompt":
                payload = json.loads(request.content)
                graph = payload["prompt"]
                stage = graph[OUTPUT_NODE]["inputs"]["filename_prefix"].rsplit("/", 1)[-1]
                submissions[payload["prompt_id"]] = stage
                conditioning = graph["conditioning"]["inputs"]
                if stage in {"portrait", "idle"}:
                    assert graph["reference"]["inputs"]["image"] == "original.jpg"
                    assert conditioning["images.image_1"] == ["reference", 0]
                    if stage == "portrait":
                        assert "images.image_2" not in conditioning
                        assert "#00FF00" not in conditioning["prompt"]
                        assert "#000000" not in conditioning["prompt"]
                        assert "#A3CEF7" in conditioning["prompt"]
                    else:
                        assert conditioning["images.image_2"] == ["accessory_reference", 0]
                        assert graph["accessory_reference"]["inputs"]["image"] == "bow-tie.webp"
                        assert "#FADEE4" in conditioning["prompt"]
                else:
                    assert graph["reference"]["inputs"]["image"] == "idle.png [output]"
                    assert conditioning["first_frame"] == conditioning["last_frame"]
                return httpx.Response(200, json={"prompt_id": payload["prompt_id"]})
            if path == "/view":
                return httpx.Response(200, content=b"media")
            task_id = path.rsplit("/", 1)[-1]
            stage = submissions[task_id]
            filename = stage + (".png" if stage in {"portrait", "idle"} else ".mp4")
            return httpx.Response(200, json={task_id: {"outputs": {
                OUTPUT_NODE: {"images": [{"type": "output", "filename": filename}]},
            }}})

        remote = {}

        async def persist(snapshot):
            remote.update(snapshot)

        async def progress(_stage, _value):
            pass

        settings = Settings(comfyui_base_url=PRIMARY, assets_dir=assets_dir)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)
            job = {"id": "abcdef123456", "photo_path": str(photo), "remote_tasks": remote}
            output = tmp_path / "output"
            portrait, videos = await provider.generate({**job, "portrait_only": True}, {"species": "dog"}, output, persist, progress)
            assert portrait.name == "portrait.png"
            assert not videos
            assert list(submissions.values()) == ["portrait"]
            idle, videos = await provider.generate({
                **job, "decoration": {"background": "pink", "accessory": "bow-tie"},
            }, {"species": "dog"}, output, persist, progress)
            assert idle.name == "idle.png"
            assert set(videos) == {"idle-video", "left", "center", "right"}

    asyncio.run(run())


@pytest.mark.parametrize("fast_host", ["primary", "secondary"])
def test_faster_gpu_claims_both_remaining_videos(tmp_path, fast_host):
    """让任一实例先完成，验证其可在慢实例结束前接手其余两段视频。"""
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(b"photo")

    async def run():
        submitted = {}
        first_pair = asyncio.Event()
        all_dispatched = asyncio.Event()
        progress = []
        snapshots = []

        async def handle(request):
            path = request.url.path
            host = request.url.host
            match path:
                case "/system_stats":
                    assert host == "secondary"
                    return httpx.Response(200, json={"devices": [{"type": "cuda"}]})
                case "/upload/image":
                    assert host == "primary"
                    return httpx.Response(200, json={"name": "photo.jpg"})
                case "/prompt":
                    payload = json.loads(request.content)
                    graph = payload["prompt"]
                    stage = graph[OUTPUT_NODE]["inputs"]["filename_prefix"].rsplit("/", 1)[-1]
                    snapshot = snapshots[-1][stage]
                    assert snapshot["provider_id"] == payload["prompt_id"]
                    assert snapshot["base_url"] == (PRIMARY if host == "primary" else SECONDARY)
                    if stage != "idle":
                        assert graph["reference"]["inputs"]["image"] == "shared/idle.png [output]"
                    submitted[payload["prompt_id"]] = (host, stage)
                    if len(submitted) == 3:
                        first_pair.set()
                    if len(submitted) == 5:
                        all_dispatched.set()
                    return httpx.Response(200, json={"prompt_id": payload["prompt_id"]})
                case "/view":
                    return httpx.Response(200, content=b"media")
                case _:
                    task_id = path.rsplit("/", 1)[-1]
                    expected_host, stage = submitted[task_id]
                    assert host == expected_host
                    if stage != "idle":
                        await first_pair.wait()
                        if host != fast_host:
                            await all_dispatched.wait()
                    name = "idle.png" if stage == "idle" else f"{stage}.mp4"
                    return httpx.Response(200, json={task_id: {"outputs": {
                        OUTPUT_NODE: {"images": [{"type": "output", "subfolder": "shared", "filename": name}]},
                    }}})

        async def persist(remote):
            snapshots.append(json.loads(json.dumps(remote)))

        async def advance(_stage, value):
            progress.append(value)

        settings = Settings(comfyui_base_url=PRIMARY, comfyui_secondary_base_url=SECONDARY)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)
            idle, videos = await asyncio.wait_for(provider.generate(
                {"id": "abcdef123456", "photo_path": str(photo)}, {"species": "dog"}, tmp_path / "out",
                persist, advance,
            ), timeout=3)
        assert {stage: host for host, stage in submitted.values()} == {
            "idle": "primary", "idle-video": "primary", "left": "secondary", "center": fast_host, "right": fast_host,
        }
        assert progress == [20, 40, 55, 70, 85]
        assert idle.is_file() and all(path.is_file() for path in videos.values())

    asyncio.run(run())


def test_simultaneous_pets_do_not_queue_a_second_job_on_busy_gpu(tmp_path):
    """两只宠物同时生成时，每个实例收完当前成片再领取下一个任务。"""

    async def run():
        active = {}
        both_active = asyncio.Event()

        async def handle(request):
            path = request.url.path
            host = request.url.host
            if path == "/system_stats":
                return httpx.Response(200, json={"devices": [{"type": "cuda"}]})
            if path == "/prompt":
                task_id = json.loads(request.content)["prompt_id"]
                assert host not in active
                active[host] = task_id
                if len(active) == 2:
                    both_active.set()
                return httpx.Response(200, json={"prompt_id": task_id})
            if path == "/view":
                assert request.url.params["filename"] == f"{active.pop(host)}.mp4"
                return httpx.Response(200, content=b"media")
            task_id = path.rsplit("/", 1)[-1]
            await both_active.wait()
            return httpx.Response(200, json={task_id: {"outputs": {
                OUTPUT_NODE: {"videos": [{"type": "output", "filename": f"{task_id}.mp4"}]},
            }}})

        async def persist(_remote):
            pass

        async def advance(_stage, _value):
            pass

        settings = Settings(comfyui_base_url=PRIMARY, comfyui_secondary_base_url=SECONDARY)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)

            async def generate(job_id, species):
                directory = tmp_path / job_id
                directory.mkdir()
                (directory / "idle.png").write_bytes(b"idle")
                remote = {"idle": {"state": "complete", "provider_id": job_id, "output_reference": "idle.png [output]"}}
                _, videos = await provider.generate(
                    {"id": job_id, "remote_tasks": remote}, {"species": species}, directory, persist, advance,
                )
                assert len(videos) == 4

            await asyncio.wait_for(asyncio.gather(
                generate("abcdef123456", "cat"), generate("123456abcdef", "dog"),
            ), timeout=3)
        assert not active

    asyncio.run(run())


def test_resume_keeps_saved_endpoint_when_new_secondary_is_offline(tmp_path):
    """验证旧主实例任务和原第二实例任务从各自历史恢复，新任务在离线时由主实例接手。"""
    (tmp_path / "idle.png").write_bytes(b"idle")
    (tmp_path / "right.mp4").write_bytes(b"right")
    job = {"id": "abcdef123456", "progress": 70, "remote_tasks": {
        "idle": {"state": "complete", "provider_id": "image-id"},
        "idle-video": {"state": "running", "provider_id": "legacy-id"},
        "left": {"state": "running", "provider_id": "saved-id", "base_url": SECONDARY},
        "right": {"state": "complete", "provider_id": "right-id", "base_url": SECONDARY},
    }}

    async def run():
        history_hosts = {}
        submissions = []

        async def handle(request):
            path = request.url.path
            host = request.url.host
            if path == "/system_stats":
                assert host == "offline"
                return httpx.Response(503)
            if path == "/upload/image":
                assert host == "primary"
                return httpx.Response(200, json={"name": "idle.png", "subfolder": "shared"})
            if path == "/prompt":
                payload = json.loads(request.content)
                assert host == "primary"
                assert payload["prompt"]["reference"]["inputs"]["image"] == "shared/idle.png"
                submissions.append(payload["prompt_id"])
                return httpx.Response(200, json={"prompt_id": payload["prompt_id"]})
            if path == "/view":
                return httpx.Response(200, content=b"media")
            task_id = path.rsplit("/", 1)[-1]
            history_hosts[task_id] = host
            return httpx.Response(200, json={task_id: {"outputs": {
                OUTPUT_NODE: {"videos": [{"type": "output", "filename": f"{task_id}.mp4"}]},
            }}})

        async def persist(_remote):
            pass

        async def advance(_stage, value):
            assert value > job["progress"]

        settings = Settings(comfyui_base_url=PRIMARY, comfyui_secondary_base_url="http://offline:8189")
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)
            _, videos = await provider.generate(job, {"species": "cat"}, tmp_path, persist, advance)
        assert len(submissions) == 1
        assert history_hosts == {"legacy-id": "primary", "saved-id": "secondary", submissions[0]: "primary"}
        assert set(videos) == {"idle-video", "left", "center", "right"}

    asyncio.run(run())


def test_cancel_interrupts_running_and_deletes_pending_tasks_per_endpoint():
    """删除未完成任务时，按实例核对队列，仅中断运行中目标任务并删除本任务的排队项。"""
    job = {
        "id": "job-cancel-1",
        "status": "generating",
        "generation_config": {"comfyui_base_url": PRIMARY},
        "remote_tasks": {
            "idle": {"state": "complete", "provider_id": "done-idle", "base_url": PRIMARY},
            "idle-video": {"state": "running", "provider_id": "run-primary", "base_url": PRIMARY},
            "left": {"state": "running", "provider_id": "pend-primary", "base_url": PRIMARY},
            "center": {"state": "submitting", "provider_id": "run-secondary", "base_url": SECONDARY},
            "right": {"state": "running", "provider_id": "already-finished", "base_url": PRIMARY},
        },
    }

    async def run():
        actions: list[tuple[str, str, str, dict | None]] = []

        async def handle(request: httpx.Request) -> httpx.Response:
            host = request.url.host
            path = request.url.path
            body = json.loads(request.content.decode("utf-8")) if request.content else None
            actions.append((host, request.method, path, body))
            if request.method == "GET" and path == "/queue":
                if host == "primary":
                    return httpx.Response(
                        200,
                        json={
                            "queue_running": [[0, "run-primary", {}, {}, []]],
                            "queue_pending": [[1, "pend-primary", {}, {}, []], [2, "other-pending", {}, {}, []]],
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "queue_running": [[0, "run-secondary", {}, {}, []]],
                        "queue_pending": [[1, "other-pet", {}, {}, []]],
                    },
                )
            if request.method == "POST" and path in {"/queue", "/interrupt"}:
                return httpx.Response(200)
            return httpx.Response(404)

        settings = Settings(comfyui_base_url=PRIMARY, comfyui_secondary_base_url=SECONDARY)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)
            await provider.cancel(job)

        assert ("primary", "POST", "/queue", {"delete": ["pend-primary"]}) in actions
        assert ("primary", "POST", "/interrupt", {"prompt_id": "run-primary"}) in actions
        assert ("secondary", "POST", "/interrupt", {"prompt_id": "run-secondary"}) in actions
        assert not any(path == "/queue" and method == "POST" and host == "secondary" for host, method, path, _ in actions)

    asyncio.run(run())


def test_cancel_ignores_offline_comfyui_and_unrelated_running_task():
    """实例离线或当前运行的是其他宠物任务时，不抛出异常且不误中断无关任务。"""
    job = {
        "id": "job-cancel-2",
        "status": "generating",
        "remote_tasks": {
            "idle": {"state": "running", "provider_id": "my-idle", "base_url": PRIMARY},
            "left": {"state": "running", "provider_id": "my-left", "base_url": SECONDARY},
        },
    }

    async def run():
        interrupt_hosts: list[str] = []

        async def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "primary":
                raise httpx.ConnectError("connection refused", request=request)
            if request.method == "GET" and request.url.path == "/queue":
                return httpx.Response(
                    200,
                    json={
                        "queue_running": [[0, "other-pet-task", {}, {}, []]],
                        "queue_pending": [],
                    },
                )
            if request.method == "POST" and request.url.path == "/interrupt":
                interrupt_hosts.append(request.url.host)
                return httpx.Response(200)
            return httpx.Response(404)

        settings = Settings(comfyui_base_url=PRIMARY, comfyui_secondary_base_url=SECONDARY)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            provider = ComfyUIGenerationProvider(settings, client=client)
            await provider.cancel(job)

        assert interrupt_hosts == []

    asyncio.run(run())
