"""文件用途：验证 ComfyUI 双卡视频并行、既有任务恢复和第二实例离线回退。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.comfyui import ComfyUIGenerationProvider
from app.comfyui_workflows import OUTPUT_NODE
from app.config import Settings

PRIMARY = "http://primary:8188"
SECONDARY = "http://secondary:8189"


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
