"""文件用途：集中定义可灵视频模型的可选参数和服务端校验规则。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MIN_VIDEO_DURATION = 3
OMNI_VIDEO_MODEL = "kling-3.0-omni"  # 前端标识与旧版 Omni API 模型名分别维护。
MAX_VIDEO_REFERENCES = 5  # 保守计入首尾帧，确保图片总数不超过 7。
VIDEO_MODELS = {
    "kling-4.0": {
        "label": "Kling 4.0", "max_duration": 30,
        "resolutions": ["720p", "1080p"], "frame_modes": ["first_last", "first"],
    },
    OMNI_VIDEO_MODEL: {
        "label": "Kling 3.0 Omni", "max_duration": 15,
        "resolutions": ["720p", "1080p", "4k"], "frame_modes": ["first_last", "first"],
        "max_references": MAX_VIDEO_REFERENCES,
    },
    "kling-3.0": {
        "label": "Kling 3.0", "max_duration": 15,
        "resolutions": ["720p", "1080p", "4k"], "frame_modes": ["first_last", "first"],
    },
    "kling-4.0-flash": {
        "label": "Kling 4.0 Flash", "max_duration": 20,
        "resolutions": ["720p"], "frame_modes": ["first"],
    },
}


class VideoOptions(BaseModel):
    """保存新任务的视频模型、时长、分辨率与帧模式，校验后供生成和重试使用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["kling-4.0", "kling-3.0", "kling-3.0-omni", "kling-4.0-flash"] = "kling-3.0"
    duration: int = Field(default=4, strict=True, ge=MIN_VIDEO_DURATION)  # 成片时长，单位为整秒。
    resolution: Literal["720p", "1080p", "4k"] = "720p"
    frame_mode: Literal["first_last", "first"] = "first_last"  # 支持首帧或首尾两帧约束。

    @model_validator(mode="after")
    def validate_model_options(self):
        """校验当前参数组合是否受所选模型支持，无额外参数，返回已校验的配置。"""
        model = VIDEO_MODELS[self.model]
        if self.duration > model["max_duration"]:
            raise ValueError(f"{model['label']} 的视频时长上限为 {model['max_duration']} 秒")
        if self.resolution not in model["resolutions"]:
            raise ValueError(f"{model['label']} 支持的分辨率为 {'、'.join(model['resolutions'])}")
        if self.frame_mode not in model["frame_modes"]:
            raise ValueError(f"{model['label']} 的图生视频仅支持首帧模式")
        return self


# 旧任务和未传视频参数的请求沿用原来的生成设置。
DEFAULT_VIDEO_OPTIONS = VideoOptions()
