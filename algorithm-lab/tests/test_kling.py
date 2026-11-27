"""文件用途：核验图片和各视频模型的协议及提交不明处理，不调用真实云端。"""

import asyncio
import base64
import json

import httpx
import pytest

from app.config import Settings
from app.image import ImageOptions
from app.kling import KlingProvider, ProviderError, SubmissionUnknown
from app.video import VideoOptions
from tests.test_workflow import photo


def test_protocols_and_query_parsers(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"code": 0, "data": {"id": "v1", "task_id": "i1"}})
        if request.url.path == "/tasks":
            return httpx.Response(200, json={"code": 0, "data": [{"id": "v1", "status": "succeeded", "outputs": [{"type": "video", "url": "https://cdn.example/video.mp4"}]}]})
        return httpx.Response(200, json={"code": 0, "data": {"task_status": "succeed", "task_result": {"images": [{"url": "https://cdn.example/idle.png"}]}}})

    async def scenario():
        path = tmp_path / "pet.jpg"
        path.write_bytes(photo())
        provider = KlingProvider(Settings(api_key="secret-test"), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert await provider.submit("idle", [path], "trace", image_prompt="保留宠物外观") == "i1"
        assert await provider.submit("video", [path], "trace2", video_prompt="缓慢眨眼") == "v1"
        idle = json.loads(requests[0].content)
        assert idle["model_name"] == "kling-v3-omni" and idle["resolution"] == "2k"
        assert idle["aspect_ratio"] == "16:9" and idle["prompt"] == "保留宠物外观"
        assert len(idle["image_list"]) == 1 and base64.b64decode(idle["image_list"][0]["image"]) == photo()
        video = json.loads(requests[1].content)
        assert requests[1].url.path == "/image-to-video/kling-3.0"
        assert video["settings"] == {"duration": 4, "resolution": "720p", "multi_shot": False}
        assert video["contents"][1]["url"] == video["contents"][2]["url"]
        assert video["contents"][1]["type"] == "first_frame" and video["contents"][2]["type"] == "last_frame"
        assert (await provider.query("video", "v1")).state == "complete"
        assert requests[-1].url.params["task_ids"] == "v1"
        assert (await provider.query("idle", "i1")).url == "https://cdn.example/idle.png"
        image_options = ImageOptions(model="kling-image-o1", resolution="1k", aspect_ratio="9:16")
        second = tmp_path / "scene.jpg"
        second.write_bytes(photo() + b"scene")
        assert await provider.submit("idle", [path, second], "trace3", image_prompt="保留花纹", image_options=image_options) == "i1"
        custom = json.loads(requests[-1].content)
        assert (custom["model_name"], custom["resolution"], custom["aspect_ratio"]) == ("kling-image-o1", "1k", "9:16")
        assert (custom["n"], custom["result_type"]) == (1, "single")
        assert [base64.b64decode(item["image"]) for item in custom["image_list"]] == [path.read_bytes(), second.read_bytes()]
        standard = ImageOptions(model="kling-v3", resolution="1k", aspect_ratio="9:16")
        assert await provider.submit("idle", [path], "trace4", image_prompt="保留花纹", image_options=standard) == "i1"
        assert requests[-1].url.path == "/v1/images/generations"
        assert json.loads(requests[-1].content) == {
            "model_name": "kling-v3", "image": base64.b64encode(photo()).decode("ascii"),
            "prompt": "保留花纹", "resolution": "1k", "aspect_ratio": "9:16", "n": 1, "external_task_id": "trace4",
        }
        assert (await provider.query("idle", "i1", image_model="kling-v3")).state == "complete"
        assert requests[-1].url.path == "/v1/images/generations/i1"
        assert all(r.headers["authorization"] == "Bearer secret-test" for r in requests)
        await provider.close()
    asyncio.run(scenario())


@pytest.mark.parametrize(("model", "resolution", "mode", "frame_types"), [
    ("kling-3.0", "1080p", "first_last", ["first_frame", "last_frame"]),
    ("kling-4.0", "1080p", "first", ["first_frame"]),
    ("kling-4.0-flash", "720p", "first", ["first_frame"]),
])
def test_video_model_routes_and_settings(tmp_path, model, resolution, mode, frame_types):
    first = tmp_path / "first.jpg"
    first.write_bytes(photo())
    def handler(request):
        assert request.url.path == f"/image-to-video/{model}"
        payload = json.loads(request.content)
        assert payload["settings"]["duration"] == 3
        assert payload["settings"]["resolution"] == resolution
        assert payload["contents"][0]["text"] == "慢慢转头"
        assert [frame["type"] for frame in payload["contents"][1:]] == frame_types
        return httpx.Response(200, json={"code": 0, "data": {"id": "v1"}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = KlingProvider(Settings(api_key="test"), client)
            options = VideoOptions(model=model, duration=3, resolution=resolution, frame_mode=mode)
            assert await provider.submit(
                "video", [first], "trace", video_options=options, video_prompt="慢慢转头",
            ) == "v1"

    asyncio.run(scenario())


@pytest.mark.parametrize(("model", "mode", "has_tail"), [
    ("kling-4.0-flash", "first", False),
    ("kling-3.0", "first_last", True),
    ("kling-4.0", "first_last", False),
])
def test_direct_video_encodes_frames_and_forwards_prompt(tmp_path, model, mode, has_tail):
    """核验独立视频请求直接发送用户提示词与原始 Base64 帧数据。"""
    first = tmp_path / "first.jpg"
    first.write_bytes(photo())
    tail = tmp_path / "tail.jpg"
    tail.write_bytes(first.read_bytes() + b"tail")

    def handler(request):
        assert request.url.path == f"/image-to-video/{model}"
        contents = json.loads(request.content)["contents"]
        assert contents[0] == {"type": "prompt", "text": "镜头向左移动"}
        assert contents[1]["type"] == "first_frame"
        assert base64.b64decode(contents[1]["url"], validate=True) == first.read_bytes()
        if mode == "first_last":
            assert contents[2]["type"] == "last_frame"
            assert base64.b64decode(contents[2]["url"], validate=True) == (tail if has_tail else first).read_bytes()
        else:
            assert len(contents) == 2
        return httpx.Response(200, json={"code": 0, "data": {"id": "v1"}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = KlingProvider(Settings(api_key="test"), client)
            references = [first, tail] if has_tail else [first]
            options = VideoOptions(model=model, duration=3, frame_mode=mode)
            assert await provider.submit(
                "video", references, "trace", video_options=options, video_prompt="镜头向左移动",
            ) == "v1"

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "server", "invalid", "missing_id", "missing_code"])
def test_submission_ambiguity_is_never_retried(failure, tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("test", request=request)
        if failure == "server":
            return httpx.Response(502)
        if failure == "invalid":
            return httpx.Response(200, text="not json")
        if failure == "missing_code":
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"code": 0, "data": {}})

    async def scenario():
        provider = KlingProvider(Settings(api_key="test"), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        path = tmp_path / "pet.jpg"
        path.write_bytes(photo())
        with pytest.raises(SubmissionUnknown):
            await provider.submit("idle", [path], "trace", image_prompt="测试")
        assert len(calls) == 1
        await provider.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("frame_mode", ["first", "first_last"])
def test_omni_video_references_and_legacy_query(tmp_path, frame_mode):
    """核验 Omni 首尾帧、普通参考图及旧接口任务查询的完整协议。"""
    paths = []
    for name in ("first", "tail", "reference"):
        path = tmp_path / f"{name}.jpg"
        path.write_bytes(photo() + name.encode())
        paths.append(path)
    sent = paths if frame_mode == "first_last" else [paths[0], paths[2]]
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            assert request.url.path == "/v1/videos/omni-video"
            payload = json.loads(request.content)
            assert payload["model_name"] == "kling-v3-omni"
            assert payload["mode"] == "pro" and payload["duration"] == "3"
            assert payload["external_task_id"] == "trace"
            assert [base64.b64decode(item["image_url"]) for item in payload["image_list"]] == [p.read_bytes() for p in sent]
            assert [item.get("type") for item in payload["image_list"]] == (
                ["first_frame", "end_frame", None] if frame_mode == "first_last" else ["first_frame", None]
            )
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "omni-id"}})
        assert request.url.path == "/v1/videos/omni-video/omni-id"
        return httpx.Response(200, json={"code": 0, "data": {"task_status": "succeed", "task_result": {"videos": [{"url": "https://cdn.example/omni.mp4"}]}}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = KlingProvider(Settings(api_key="test"), client)
            options = VideoOptions(model="kling-3.0-omni", duration=3, resolution="1080p", frame_mode=frame_mode)
            assert await provider.submit("video", sent, "trace", video_options=options, video_prompt="参考图片") == "omni-id"
            task = await provider.query("video", "omni-id", video_model=options.model)
            assert task.state == "complete" and task.url == "https://cdn.example/omni.mp4"

    asyncio.run(scenario())
    assert len(calls) == 2


def test_query_extracts_cost_and_account_costs(tmp_path):
    """核验不同接口扣费字段解析（不重复计数）以及 /account/costs 资源包余量查询。"""
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/v1/images/omni-image/img-1":
            return httpx.Response(200, json={
                "code": 0,
                "data": {
                    "task_status": "succeed",
                    "task_result": {"images": [{"url": "https://cdn.example/img.png"}]},
                    "final_unit_deduction": "8",
                },
            })
        if request.url.path == "/tasks":
            return httpx.Response(200, json={
                "code": 0,
                "data": [{
                    "id": "vid-1",
                    "status": "succeeded",
                    "outputs": [{"type": "video", "url": "https://cdn.example/vid.mp4"}],
                    "billing": [
                        {"charge_type": "unit", "amount": "6", "package_type": "video"},
                        {"charge_type": "cash", "cash_type": "balance", "amount": "1.20", "currency": "CNY", "list_price": "1.50"},
                    ],
                    "final_unit_deduction": "6",
                    "usage": {"input_duration": 0, "output_duration": 4},
                }],
            })
        if request.url.path == "/v1/videos/omni-video/vid-fail":
            return httpx.Response(200, json={
                "code": 0,
                "data": {
                    "task_status": "failed",
                    "task_status_msg": "生成失败",
                    "final_unit_deduction": "0",
                },
            })
        if request.url.path == "/account/costs":
            return httpx.Response(200, json={
                "code": 0,
                "data": {
                    "code": 0,
                    "resource_pack_subscribe_infos": [
                        {
                            "resource_pack_name": "视频生成资源包",
                            "resource_pack_id": "pack-v",
                            "resource_pack_type": "decreasing_total",
                            "resource_pack_tier": "flagship",
                            "resource_pack_applicable_models": "Kling 4.0",
                            "total_quantity": 200.0,
                            "remaining_quantity": 118.5,
                            "invalid_time": 1800000000000,
                            "status": "online",
                        },
                        {
                            "resource_pack_name": "图片资源包",
                            "resource_pack_id": "pack-i",
                            "resource_pack_type": "decreasing_total",
                            "resource_pack_tier": "general",
                            "resource_pack_applicable_models": "Image 3.0 Omni",
                            "total_quantity": 100.0,
                            "remaining_quantity": 0.0,
                            "status": "runOut",
                        },
                    ],
                },
            })
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = KlingProvider(Settings(api_key="secret-test"), client)
            img_task = await provider.query("idle", "img-1")
            assert img_task.cost["unit_amount"] == "8"
            assert img_task.cost["label"] == "8 Units"

            vid_task = await provider.query("video", "vid-1")
            assert vid_task.cost["unit_amount"] == "6"
            assert vid_task.cost["cash_amounts"] == {"CNY": "1.2"}
            assert vid_task.cost["list_price_amounts"] == {"CNY": "1.5"}
            assert vid_task.cost["usage"] == {"input_duration": "0", "output_duration": "4"}
            assert vid_task.cost["label"] == "6 Units + ¥1.20"

            fail_task = await provider.query("video", "vid-fail", video_model="kling-3.0-omni")
            assert fail_task.state == "failed"
            assert fail_task.cost["is_zero"] is True
            assert fail_task.cost["label"] == "0（未扣费）"

            packs = await provider.account_costs(start_time=1000, end_time=2000)
            assert len(packs) == 2
            assert packs[0]["category"] == "video"
            assert packs[0]["remaining_text"] == "118.5"
            assert packs[0]["total_text"] == "200"
            assert packs[0]["status"] == "online"
            assert packs[1]["category"] == "image"
            assert requests[-1].url.params["start_time"] == "1000"
            assert requests[-1].url.params["end_time"] == "2000"
            assert all(r.headers["authorization"] == "Bearer secret-test" for r in requests)

    asyncio.run(scenario())


def test_account_costs_handles_nested_error():
    """核验 /account/costs 返回业务错误码时抛出可识别异常。"""

    def handler(request):
        return httpx.Response(200, json={"code": 0, "data": {"code": 1102, "msg": "permission denied"}})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = KlingProvider(Settings(api_key="test"), client)
            with pytest.raises(ProviderError, match="1102"):
                await provider.account_costs()

    asyncio.run(scenario())
