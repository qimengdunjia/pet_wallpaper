"""文件用途：定义图生图模型的分辨率、画幅和默认参数。"""

from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, model_validator

AspectRatio = Literal["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "21:9", "auto"]
IMAGE_ASPECT_RATIOS = get_args(AspectRatio)  # 图片输出宽高比，auto 由模型选择。
MAX_IMAGE_REFERENCES = 10  # Omni 图片接口允许的参考图数量上限。
STANDARD_IMAGE_MODEL = "kling-v3"  # 普通 3.0 使用独立的单参考图接口。
IMAGE_MODELS = {
    "kling-v3-omni": {"label": "Kling Image 3.0 Omni", "resolutions": ["1k", "2k", "4k"]},
    STANDARD_IMAGE_MODEL: {
        "label": "Kling Image 3.0",
        "resolutions": ["1k", "2k"],
        "aspect_ratios": [ratio for ratio in IMAGE_ASPECT_RATIOS if ratio != "auto"],
    },
    "kling-image-o1": {"label": "Kling Image O1", "resolutions": ["1k", "2k"]},
}


class ImageOptions(BaseModel):
    """保存图生图模型、分辨率和宽高比，供提交和按原参数重做使用。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: Literal["kling-v3-omni", "kling-v3", "kling-image-o1"] = "kling-v3-omni"
    resolution: Literal["1k", "2k", "4k"] = "2k"
    aspect_ratio: AspectRatio = "16:9"

    @model_validator(mode="after")
    def validate_model_options(self):
        """校验分辨率和画幅是否受所选模型支持，无额外参数，返回已校验的配置。"""
        model = IMAGE_MODELS[self.model]
        if self.resolution not in model["resolutions"]:
            supported = "、".join(value.upper() for value in model["resolutions"])
            raise ValueError(f"{model['label']} 支持的分辨率为 {supported}")
        if self.aspect_ratio not in model.get("aspect_ratios", IMAGE_ASPECT_RATIOS):
            raise ValueError(f"{model['label']} 需要选择具体画幅")
        return self


DEFAULT_IMAGE_OPTIONS = ImageOptions()
