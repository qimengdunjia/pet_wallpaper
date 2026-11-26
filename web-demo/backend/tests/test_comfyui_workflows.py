"""文件用途：离线验证 ComfyUI 视频流程的采样尺寸、画面帧来源和成片规格。"""

from app.comfyui_workflows import OUTPUT_NODE, image_workflow, video_workflow
from app.decoration import (
    ACCESSORY_NAMES,
    BACKGROUND_NAMES,
    BACKGROUNDS,
    PORTRAIT_IMAGE_SIZE,
    portrait_prompt,
    styled_idle_prompt,
)


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
    """验证待机图提示词按猫狗与配饰分支正确注入分工、背景与姿态，并在无配饰时不引用 Picture 2。"""
    for key, color in BACKGROUNDS.items():
        name = BACKGROUND_NAMES[key]
        cat_without = styled_idle_prompt("", {"background": key, "accessory": "none"}, "cat")
        assert cat_without.startswith("<Picture 1> 为宠物参考图。生成一张横向 16:9 的完整画面，严格遵循以下分工：")
        assert f"{color}（{name}）" in cat_without
        assert "<Picture 2>" not in cat_without
        assert "动物不佩戴任何装饰物" in cat_without
        assert "耳朵形态与毛色花纹" in cat_without
        assert "嘴巴自然闭合" in cat_without
        assert "舌尖" not in cat_without

        dog_without = styled_idle_prompt("", {"background": key, "accessory": "none"}, "dog")
        assert dog_without.startswith("<Picture 1> 为宠物参考图。生成一张横向 16:9 的完整画面，严格遵循以下分工：")
        assert f"{color}（{name}）" in dog_without
        assert "<Picture 2>" not in dog_without
        assert "耳朵形态与毛色细节" in dog_without
        assert "正中轻露一小截小舌尖" in dog_without

        for acc_key, acc_name in ACCESSORY_NAMES.items():
            if acc_key == "none":
                continue
            dog_with = styled_idle_prompt("", {"background": key, "accessory": acc_key}, "dog")
            assert dog_with.startswith(f"<Picture 1> 为宠物参考图，<Picture 2> 为{acc_name}装饰参考图。")
            assert f"{color}（{name}）" in dog_with
            assert f"装饰物佩戴（仅提取 <Picture 2> 中的{acc_name}）：" in dog_with
            assert dog_with.index("构图与姿态：") < dog_with.index("装饰物佩戴")
            assert "正中轻露一小截小舌尖" in dog_with

            cat_with = styled_idle_prompt("", {"background": key, "accessory": acc_key}, "cat")
            assert cat_with.startswith(f"<Picture 1> 为宠物参考图，<Picture 2> 为{acc_name}装饰参考图。")
            assert "耳朵形态与毛色花纹" in cat_with
            assert "嘴巴自然闭合" in cat_with
            assert "舌尖" not in cat_with

    glasses_prompt = styled_idle_prompt("", {"background": "lavender", "accessory": "glasses"}, "dog")
    assert "保留墨镜原本的镜框颜色造型与深色镜片" in glasses_prompt


def test_portrait_prompt_adapts_species_and_square_upper_body_framing():
    """验证正面照提示词按猫狗严格还原外观，采用 1:1 头部与上半身构图且不包含底部黑块。"""
    cat_prompt = portrait_prompt("", "cat")
    assert cat_prompt.startswith("<Picture 1> 为宠物参考图。")
    assert "将 <Picture 1> 中的猫咪作为唯一主体放入 1:1 正方形的新场景中" in cat_prompt
    assert "只露出头部、颈部和上半身胸部" in cat_prompt
    assert "嘴巴自然闭合" in cat_prompt
    assert "#A3CEF7（浅蓝色）" in cat_prompt
    assert "#000000" not in cat_prompt

    dog_prompt = portrait_prompt("", "dog")
    assert "将 <Picture 1> 中的狗狗作为唯一主体放入 1:1 正方形的新场景中" in dog_prompt
    assert "保持 <Picture 1> 原有的面部结构、嘴部形态与自然放松的神态" in dog_prompt
    assert "#A3CEF7（浅蓝色）" in dog_prompt
    assert "#000000" not in dog_prompt

    graph_portrait = image_workflow("pet.jpg", cat_prompt, PORTRAIT_IMAGE_SIZE, 49, "demo/portrait")
    assert (graph_portrait["conditioning"]["inputs"]["width"], graph_portrait["conditioning"]["inputs"]["height"]) == (1024, 1024)
    assert graph_portrait["conditioning"]["inputs"]["prompt"] == cat_prompt
    assert graph_portrait["conditioning"]["inputs"]["prompt"].count("<Picture 1> 为宠物参考图") == 1


def test_image_workflow_avoids_duplicate_picture_prefix():
    """验证已含 Picture 1 声明的装扮提示词不会被工作流重复拼接前缀，旧提示词仍保持自动补全。"""
    styled = styled_idle_prompt("", {"background": "blue", "accessory": "bow-tie"}, "dog")
    graph_styled = image_workflow("pet.jpg", styled, (1344, 768), 49, "demo/idle", accessory_reference="bow-tie.webp")
    assert graph_styled["conditioning"]["inputs"]["prompt"] == styled
    assert graph_styled["conditioning"]["inputs"]["prompt"].count("<Picture 1> 为宠物参考图") == 1

    graph_legacy = image_workflow("pet.jpg", "生成一张宠物正面照。", (1344, 768), 49, "demo/portrait")
    assert graph_legacy["conditioning"]["inputs"]["prompt"] == "<Picture 1> 为宠物参考图。生成一张宠物正面照。"
