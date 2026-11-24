"""文件用途：离线验证 ComfyUI 视频流程的采样尺寸、画面帧来源和成片规格。"""

from app.comfyui_workflows import OUTPUT_NODE, video_workflow


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
