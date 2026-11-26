"""文件用途：离线验证 ComfyUI 视频流程的采样尺寸、画面帧来源和成片规格。"""

from app.comfyui_workflows import OUTPUT_NODE, video_workflow
from app.decoration import BACKGROUND_NAMES, BACKGROUNDS, styled_idle_prompt


def test_video_encodes_model_generated_endpoints():
    """验证首尾共用按采样尺寸裁切的参考图，成片使用模型生成的完整帧序列。"""
    graph = video_workflow("demo/idle.png", "轻轻呼吸", (1920, 1080), 42, "demo/idle-video")

    conditioning = graph["conditioning"]["inputs"]
    assert (conditioning["width"], conditioning["height"]) == (1344, 768)
    assert conditioning["first_frame"] == conditioning["last_frame"] == ["scale_reference", 0]
    reference_scale = graph["scale_reference"]
    assert reference_scale["class_type"] == "ImageScale"
    assert reference_scale["inputs"] == {
        "image": ["reference", 0], "width": 1344, "height": 768, "upscale_method": "bicubic", "crop": "center",
    }

    # 沿成片输入回溯，确认重新采样后的模型帧全部经过同一次缩放。
    assert graph[OUTPUT_NODE]["inputs"]["video"] == ["video", 0]
    assert graph["video"]["inputs"] == {"images": ["scale_frames", 0], "fps": 24}
    assert graph["scale_frames"]["inputs"]["image"] == ["components", 0]
    assert graph["scale_frames"]["inputs"]["width"] == 1920
    assert graph["scale_frames"]["inputs"]["height"] == 1080
    assert graph["scale_frames"]["inputs"]["crop"] == "center"
    assert graph["components"]["inputs"]["video"] == ["resample", 0]
    assert graph["resample"]["inputs"]["num_frames"] == 96
    assert graph["resample"]["inputs"]["video"] == ["preview", 0]
    assert graph["preview"]["inputs"]["images"] == ["decode", 0]


def test_styled_idle_prompt_handles_all_backgrounds_and_accessory_states():
    """验证待机图提示词按猫狗分支正确注入背景色值与名称，并在无配饰时不引用 Picture 2。"""
    for key, color in BACKGROUNDS.items():
        name = BACKGROUND_NAMES[key]
        cat_with = styled_idle_prompt("", {"background": key, "accessory": "bow-tie"}, "cat")
        assert f"{color}（{name}）" in cat_with
        assert "<Picture 2>" in cat_with
        assert "嘴巴自然闭合" in cat_with
        assert "舌头" not in cat_with

        dog_with = styled_idle_prompt("", {"background": key, "accessory": "bow-tie"}, "dog")
        assert f"{color}（{name}）" in dog_with
        assert "<Picture 2>" in dog_with
        assert "面部表情：狗狗呈现开心" in dog_with

        cat_without = styled_idle_prompt("", {"background": key, "accessory": "none"}, "cat")
        assert f"{color}（{name}）" in cat_without
        assert "<Picture 2>" not in cat_without
        assert "去除 <Picture 1> 原有的背景与多余装饰物" in cat_without
        assert "猫咪" in cat_without
        assert "嘴巴自然闭合" in cat_without

        dog_without = styled_idle_prompt("", {"background": key, "accessory": "none"}, "dog")
        assert f"{color}（{name}）" in dog_without
        assert "<Picture 2>" not in dog_without
        assert "狗狗" in dog_without
        assert "猫咪" not in dog_without
        assert "面部表情：狗狗呈现开心" in dog_without
