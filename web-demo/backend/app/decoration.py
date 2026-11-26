"""文件用途：定义背景和装扮选项、合成正面照预览并构造待机图提示词。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel

from .media import AssetValidationError

Background = Literal["cream", "pink", "blue", "lavender"]
Accessory = Literal["none", "bow-tie", "bandana", "glasses", "santa-hat"]

# 色值取自装扮页原稿，预览与生成在服务端共用同一套配色。
BACKGROUNDS = {
    "cream": "#FCF6ED",
    "pink": "#FADEE4",
    "blue": "#A3CEF7",
    "lavender": "#C8C2F5",
}
ACCESSORY_NAMES = {
    "none": "无配饰",
    "bow-tie": "蝴蝶结",
    "bandana": "三角巾",
    "glasses": "墨镜",
    "santa-hat": "圣诞帽",
}
THUMBNAILS = {"background-pet", *(key for key in ACCESSORY_NAMES if key != "none")}


class Decoration(BaseModel):
    """接收背景和配饰标识，默认与设计图所选的浅蓝背景、无配饰一致。"""

    background: Background = "blue"
    accessory: Accessory = "none"


def portrait_prompt(base_prompt: str = "") -> str:
    """构造正面照生成提示词，直接输出干净纯色背景的中景宠物正面照，不使用绿幕或底部黑色块。"""
    return (
        "仅以用户原照 <Picture 1> 中的动物为唯一主体，生成一张宠物正面照。"
        "严格保留原照的轮廓造型、头脸比例、五官样式、眼睛形态大小与配色、配色分布、花纹图案、耳朵形状以及原本的表面质感与视觉风格，"
        "不做写实化或卡通化转绘，不擅自添加原照中不存在的纹理、花纹或额外特征。"
        "构图与比例：采用平视中景构图，不要大头特写；宠物正面居中趴卧或端坐，正视镜头，头部端正，不歪头、不侧身，"
        "双眼自然睁开，保持原照原有的面部结构与自然友善的神态，轮廓完整。"
        "宠物整体大小适中，约占画面高度的 55% 至 65%、宽度的 30% 至 40%，"
        "头顶上方、耳朵两侧以及画面下方都要留出充足均匀的纯色背景边距，不贴边、不裁切。"
        f"背景与风格：背景为干净、均匀的纯色 {BACKGROUNDS['blue']}（浅蓝色），"
        "画面整体干净通透，无阴影、无纹理、无渐变、无边框、无遮挡物。"
        "不要给宠物穿衣或佩戴任何饰品，去除原照背景，画面中无其他动物、人物、文字或水印。"
    )


def styled_idle_prompt(base_prompt: str, decoration: dict) -> str:
    """按工作流的双参考图分工，将已有提示词和已确认装扮组装成待机图提示词。"""
    background = BACKGROUNDS[decoration["background"]]
    accessory = decoration["accessory"]
    accessory_rule = "动物不佩戴任何配饰。" if accessory == "none" else (
        f"<Picture 2> 是{ACCESSORY_NAMES[accessory]}的唯一参考。去除该图原有背景，将配饰佩戴在宠物对应位置。"
        "保留配饰的外形、结构和主色调，按宠物比例自然贴合，保持遮挡和阴影合理。"
        "配饰的图像媒介、材质、边缘处理和细节精度需要与 <Picture 1> 的主体一致。"
    )
    return (
        f"以下图像要求优先于补充描述。仅以用户原照 <Picture 1> 中的动物为唯一主体。"
        "严格保留原照的轮廓与头脸比例、五官、眼耳形状、颜色花纹、纹理和视觉风格，不做写实化或卡通化转绘。"
        f"背景为干净、均匀的纯色 {background}。{accessory_rule}"
        "横向 16:9 构图，画面最下方约 10% 是横贯画面的纯黑色块，边缘平直。"
        "动物正面居中，只露头、颈、少量胸部和双前爪。两只前爪自然对称搭在黑色块上沿，其余身体在色块后方。"
        "头部端正，眼睛自然睁开，保持原照面部结构和神态。去除原照背景，无其他动物、人物、文字或水印。"
        f"\n补充描述：{base_prompt}"
    )


def styled_video_prompt(base_prompt: str) -> str:
    """为动作提示词补充待机图外观一致性要求，返回完整视频提示词。"""
    return (
        base_prompt + "\n全程沿用首尾帧的背景颜色、宠物配饰、原有视觉风格和画面景别。"
        "保留画面底部前景与身体的遮挡关系，不露出原来隐藏的躯干、后肢或尾巴。"
    )


def prepare_portrait(source: Path, target: Path) -> None:
    """将正面照原图规范为 RGBA PNG 并原子写入 target，不做绿幕抠图。"""
    with Image.open(source) as image:
        portrait = image.convert("RGBA")
    alpha = portrait.getchannel("A")
    bounds = alpha.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if not bounds:
        raise AssetValidationError("正面照未识别到宠物，请重试生成正面照")
    temporary = target.with_suffix(".part")
    try:
        portrait.save(temporary, format="PNG")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def compose_decoration(portrait: Image.Image, assets_dir: Path, decoration: Decoration) -> Image.Image:
    """将 RGBA 宠物图层与指定款式合成，返回全尺寸 RGB 预览图。"""
    result = Image.new("RGBA", portrait.size, BACKGROUNDS[decoration.background])
    result.alpha_composite(portrait)
    if decoration.accessory != "none":
        # 相对于前景高度定位，帽子、眼镜与颈部饰品使用各自的中心线和宽度。
        placements = {
            "bow-tie": (0.46, 0.30),
            "bandana": (0.53, 0.36),
            "glasses": (0.26, 0.46),
            "santa-hat": (0.06, 0.46),
        }
        center_y, width_ratio = placements[decoration.accessory]
        alpha = portrait.getchannel("A").point(lambda value: 255 if value >= 128 else 0)
        left, top, right, bottom = alpha.getbbox()
        height = bottom - top
        with Image.open(assets_dir / "decoration" / f"{decoration.accessory}.webp") as source:
            width = max(1, round(height * width_ratio))
            accessory = ImageOps.contain(source.convert("RGBA"), (width, height), Image.Resampling.LANCZOS)
        x = (left + right - accessory.width) // 2
        y = max(0, round(top + height * center_y - accessory.height / 2))
        result.alpha_composite(accessory, (x, y))
    return result.convert("RGB")
