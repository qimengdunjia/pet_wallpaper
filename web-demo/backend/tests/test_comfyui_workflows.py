"""文件用途：离线验证 ComfyUI 视频流程的画面帧来源和成片规格。"""

from app.comfyui_workflows import OUTPUT_NODE, video_workflow


def test_video_encodes_model_generated_endpoints():
    """验证待机图约束首尾姿态，成片直接使用模型生成的完整帧序列。"""
    graph = video_workflow("demo/idle.png", "轻轻呼吸", (1920, 1080), 42, "demo/idle-video")

    conditioning = graph["conditioning"]["inputs"]
    assert conditioning["first_frame"] == conditioning["last_frame"] == ["reference", 0]

    # 沿成片输入回溯，确认重新采样后的模型帧全部经过同一次缩放。
    assert graph[OUTPUT_NODE]["inputs"]["video"] == ["video", 0]
    assert graph["video"]["inputs"] == {"images": ["scale_frames", 0], "fps": 24}
    assert graph["scale_frames"]["inputs"]["image"] == ["components", 0]
    assert graph["scale_frames"]["inputs"]["width"] == 1920
    assert graph["scale_frames"]["inputs"]["height"] == 1080
    assert graph["components"]["inputs"]["video"] == ["resample", 0]
    assert graph["resample"]["inputs"]["num_frames"] == 96
    assert graph["resample"]["inputs"]["video"] == ["preview", 0]
    assert graph["preview"]["inputs"]["images"] == ["decode", 0]
