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
BACKGROUND_NAMES = {
    "cream": "米白色",
    "pink": "浅粉色",
    "blue": "浅蓝色",
    "lavender": "浅紫色",
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


def styled_idle_prompt(base_prompt: str, decoration: dict, species: str | None = None) -> str:
    """按物种和已确认的背景与配饰组装待机图提示词。"""
    bg_key = decoration["background"]
    bg = f"{BACKGROUNDS[bg_key]}（{BACKGROUND_NAMES[bg_key]}）"
    is_dog = species == "dog" or (not species and "狗狗" in base_prompt)
    pet = "狗狗" if is_dog else "猫咪"
    has_accessory = decoration["accessory"] != "none"

    if is_dog:
        pose_and_expression = (
            "构图与姿态：狗狗位于画面正中央，只露出头部、颈部和少量胸部，两只前爪自然对称地搭在画面下方纯黑色色块（#000000）的上沿，身体其余部分隐藏在纯黑色色块后方。"
            "狗狗正视镜头，头部端正，不歪头、不侧身；鼻尖、双眼中心与画面竖直中轴线对齐，整体呈现自然的左右对称感。\n\n"
            "面部表情：狗狗呈现开心、兴奋、活泼且亲切的状态，仿佛正开心地看着前方。嘴巴自然微微张开，嘴角轻轻上扬呈微笑神态，舌头从嘴巴正中轻轻露出一小截舌尖，保持自然放松；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式，眼神明亮友善。避免夸张大张嘴、过度吐舌、明显露齿或凶狠表情，舌头不要明显偏向左侧或右侧。"
        )
    else:
        pose_and_expression = (
            "构图与姿态：猫咪位于画面正中央，只露出头部、颈部和少量胸部，两只前爪自然对称地搭在画面下方纯黑色色块（#000000）的上沿，身体其余部分隐藏在纯黑色色块后方。"
            "猫咪正视镜头，头部端正，不歪头、不侧身；鼻尖、双眼中心与画面竖直中轴线对齐，整体呈现自然的左右对称感。"
            "嘴巴自然闭合，保持 <Picture 1> 原有的面部结构与自然放松的神态；双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )

    if has_accessory:
        intro_tail = f"新场景中，并在{pet}身上清晰佩戴 <Picture 2> 中的装饰物，且装饰物的视觉风格与 <Picture 1> {pet}主体完全一致。"
        subject_extra = "不做任何风格改动；除必须佩戴在身上的 <Picture 2> 装饰外，不擅自添加 <Picture 1> 中不存在的纹理、花纹或额外特征。"
        accessory_section = (
            f"\n\n装饰必须佩戴且风格与 <Picture 1> 主体一致：提取 <Picture 2> 中的装饰物（去除 <Picture 2> 原有背景），"
            f"必须清晰、完整地佩戴在{pet}身上最合理的对应位置（如帽子戴在头顶并自然贴合或避让耳朵，围巾、项圈或领结戴在颈部，眼镜戴在眼部等），绝对不可遗漏或省略。"
            f"保留 <Picture 2> 装饰物的外形轮廓、结构特征与主色调，按{pet}头身比例精准缩放贴合，呈现自然的遮挡关系与贴合阴影；"
            f"装饰物的视觉风格、图像媒介、表面材质质感、抽象程度、边缘轮廓特征与细节精细度必须 100% 转化为与 <Picture 1> 中的{pet}主体完全一致，"
            f"表面平整干净、质感自然，与{pet}主体浑然一体。"
        )
        blend_subject = f"佩戴 <Picture 2> 装饰的{pet}"
        cleanup = "去除 <Picture 1> 和 <Picture 2> 原有的背景与多余元素。除 <Picture 2> 指定的装饰外，画面中无其他道具、无其他动物、无人物、无文字、无水印。"
    else:
        intro_tail = "新场景中。"
        subject_extra = "不做任何风格改动，不擅自添加 <Picture 1> 中不存在的纹理、花纹或额外特征。"
        accessory_section = ""
        blend_subject = pet
        cleanup = "去除 <Picture 1> 原有的背景与多余装饰物。画面中无其他道具、无其他动物、无文字、无水印。"

    return (
        f"保持与 <Picture 1> 完全一致的视觉风格、图像媒介、表面质感、抽象程度、边缘轮廓特征与色彩体系，将 <Picture 1> 中的{pet}作为唯一主体放入横向 16:9 的{intro_tail}\n\n"
        f"主体严格还原：{pet}的外观必须与 <Picture 1> 一模一样，完全保留 <Picture 1> 中{pet}的轮廓造型、头脸比例、五官样式、眼睛形态大小与配色、配色分布、花纹图案、耳朵形状以及原本的表面质感与细节精细度，{subject_extra}"
        f"{accessory_section}\n\n"
        f"{pose_and_expression}\n\n"
        f"场景与全局风格统一：背景为干净、均匀的{bg}，通透不杂乱；画面最下方 10% 高度为横向贯穿整个画面的纯黑色色块（#000000），边缘平直整齐。"
        f"{bg}背景以及整体明暗光线必须 100% 沿用 <Picture 1> 原有的视觉风格、清晰度、材质纹理、轮廓特征与色彩饱和度来呈现，"
        f"不出现与 <Picture 1> 不一致的模糊或风格割裂感，使{blend_subject}与干净的{bg}背景自然融为一体，全图如同原生于 <Picture 1> 的同一幅完整作品。\n\n"
        f"{cleanup}"
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
