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
# 每种配饰的名称、佩戴位置和细节保留说明，供有配饰分支精确生成提示词。
ACCESSORY_PROMPTS: dict[str, tuple[str, str, str]] = {
    "bow-tie": ("蝴蝶结", "自然系在动物颈部正中", ""),
    "bandana": ("三角巾", "自然围系在动物颈部正中", ""),
    "glasses": ("墨镜", "自然架在动物鼻梁与眼部前方", "保留墨镜原本的镜框颜色造型与深色镜片，"),
    "santa-hat": ("圣诞帽", "戴在动物头顶正中，自然贴合并完整露出一双耳朵", ""),
}
THUMBNAILS = {"background-pet", *(key for key in ACCESSORY_NAMES if key != "none")}
# 装扮页左侧预览框接近 1:1（554u×574u），正面照直接按 1:1 生成，免去二次放大和裁切。
PORTRAIT_IMAGE_SIZE = (1024, 1024)


class Decoration(BaseModel):
    """接收背景和配饰标识，默认与设计图所选的浅蓝背景、无配饰一致。"""

    background: Background = "blue"
    accessory: Accessory = "none"


def portrait_prompt(base_prompt: str = "", species: str | None = None) -> str:
    """构造 1:1 正面照生成提示词，严格还原宠物外观，仅露出头部与上半身，适配装扮页方形预览框。"""
    if species == "dog" or (not species and "狗狗" in base_prompt):
        pet = "狗狗"
        expression = (
            "保持 <Picture 1> 原有的面部结构、嘴部形态与自然放松的神态；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )
    elif species == "cat" or (not species and "猫咪" in base_prompt):
        pet = "猫咪"
        expression = (
            "嘴巴自然闭合，保持 <Picture 1> 原有的面部结构与自然放松的神态；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )
    else:
        pet = "宠物"
        expression = (
            "保持 <Picture 1> 原有的面部结构、嘴部形态与自然放松的神态；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )
    bg = f"{BACKGROUNDS['blue']}（{BACKGROUND_NAMES['blue']}）"
    return (
        f"<Picture 1> 为宠物参考图。保持与 <Picture 1> 完全一致的视觉风格、图像媒介、表面质感、抽象程度、边缘轮廓特征与色彩体系，"
        f"将 <Picture 1> 中的{pet}作为唯一主体放入 1:1 正方形的新场景中。\n\n"
        f"主体严格还原：{pet}的外观必须与 <Picture 1> 一模一样，完全保留 <Picture 1> 中{pet}的轮廓造型、头脸比例、五官样式、"
        f"眼睛形态大小与配色、配色分布、花纹图案、耳朵形状以及原本的表面质感与细节精细度，"
        f"不做任何风格改动，不擅自添加 <Picture 1> 中不存在的纹理、花纹或额外特征。\n\n"
        f"构图与姿态：{pet}位于画面水平正中央，只露出头部、颈部和上半身胸部，下半身自然延伸至画面底边之外，不露出前爪与下半身。"
        f"头顶上方与耳朵两侧留出适度均匀的纯色背景空间，不贴边、不裁切耳朵。"
        f"{pet}正视镜头，头部端正，不歪头、不侧身；鼻尖、双眼中心与画面竖直中轴线对齐，整体呈现自然的左右对称感。"
        f"{expression}\n\n"
        f"场景与全局风格统一：背景为干净、均匀的{bg}，通透不杂乱，铺满主体周围的全部背景区域。"
        f"{bg}背景以及整体明暗光线必须 100% 沿用 <Picture 1> 原有的视觉风格、清晰度、材质纹理、轮廓特征与色彩饱和度来呈现，"
        f"不出现与 <Picture 1> 不一致的模糊或风格割裂感，使{pet}与干净的{bg}背景自然融为一体，"
        f"全图如同原生于 <Picture 1> 的同一幅完整作品。\n\n"
        "去除 <Picture 1> 原有的背景与多余装饰物（包括原有项圈、胸背带或衣物）。画面中无其他道具、无其他动物、无文字、无水印。"
    )


def styled_idle_prompt(base_prompt: str, decoration: dict, species: str | None = None) -> str:
    """按物种和已确认的背景与配饰组装待机图提示词。"""
    bg_key = decoration["background"]
    bg = f"{BACKGROUNDS[bg_key]}（{BACKGROUND_NAMES[bg_key]}）"
    is_dog = species == "dog" or (not species and "狗狗" in base_prompt)
    accessory_key = decoration["accessory"]
    has_accessory = accessory_key != "none"

    if is_dog:
        expression = (
            "保持 <Picture 1> 原有的头顶轮廓、耳朵形态与毛色细节、眼距与脸颊毛发走向完全不变，"
            "仅在原有嘴部位置自然微微张开一点、正中轻露一小截小舌尖，呈现自然放松且亲切的神态；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )
    else:
        expression = (
            "保持 <Picture 1> 原有的头顶轮廓、耳朵形态与毛色花纹、眼距、脸颊毛发走向与面部结构完全不变，"
            "嘴巴自然闭合，保持 <Picture 1> 原有的自然放松神态；"
            "双眼自然睁开，完全沿用 <Picture 1> 的眼睛造型、大小、配色与表现方式。"
        )

    if has_accessory:
        acc_name, acc_pos, acc_extra = ACCESSORY_PROMPTS.get(
            accessory_key,
            (ACCESSORY_NAMES.get(accessory_key, "装饰物"), "佩戴在动物身上最合理的对应位置", ""),
        )
        header = (
            f"<Picture 1> 为宠物参考图，<Picture 2> 为{acc_name}装饰参考图。"
            f"生成一张横向 16:9 的完整画面，严格遵循以下分工：背景为干净、均匀的 {bg} 纯色背景；"
            f"动物主体的外貌与视觉风格保持与 <Picture 1> 一致不变；动物自然佩戴 <Picture 2> 中的{acc_name}。"
        )
        subject_extra = (
            f"绝对不受 <Picture 2> 的风格或色调影响；除佩戴 <Picture 2> 中的{acc_name}外，"
            "不要给动物穿其他衣物或饰品，不擅自添加 <Picture 1> 中不存在的纹理、花纹或额外特征。"
        )
        accessory_section = (
            f"装饰物佩戴（仅提取 <Picture 2> 中的{acc_name}）：去除 <Picture 2> 原有背景，"
            f"将 <Picture 2> 中的{acc_name}清晰、完整地{acc_pos}。"
            f"忠实保留 <Picture 2> 中{acc_name}原本的外形轮廓、结构细节、平整干净的原始表面与主色调"
            f"（不改变其原有材质质感，不凭空添加凹凸花纹、斑点或多余纹路），{acc_extra}"
            "按动物头身比例自然缩放并贴合，呈现合理的遮挡关系与轻柔贴合阴影，"
            "仅调整其图像媒介与整体明暗光线，使其自然融入 <Picture 1> 的画面风格中。"
        )
        blend_subject = f"佩戴{acc_name}的动物主体"
        cleanup = (
            f"去除 <Picture 1> 和 <Picture 2> 原有的背景与多余元素。"
            f"除 <Picture 2> 中的{acc_name}外，画面中无其他道具、无其他动物、无人物、无文字、无水印。"
        )
    else:
        header = (
            "<Picture 1> 为宠物参考图。生成一张横向 16:9 的完整画面，严格遵循以下分工："
            f"背景为干净、均匀的 {bg} 纯色背景；"
            "动物主体的外貌与视觉风格保持与 <Picture 1> 一致不变；动物不佩戴任何装饰物。"
        )
        subject_extra = "不要给动物穿衣或佩戴任何饰品，不擅自添加 <Picture 1> 中不存在的纹理、花纹或额外特征。"
        accessory_section = ""
        blend_subject = "动物主体"
        cleanup = "去除 <Picture 1> 原有的背景与多余元素。画面中无其他道具、无其他动物、无人物、无文字、无水印。"

    subject_section = (
        "主体严格还原（外貌与风格保持 <Picture 1> 不变）：<Picture 1> 中的动物作为唯一动物主体，"
        "其外观与视觉风格必须与 <Picture 1> 一模一样，完全保留 <Picture 1> 的视觉风格、图像媒介、表面质感、"
        "抽象程度、边缘轮廓特征、色彩体系，以及动物的轮廓造型、头脸比例、五官样式、眼睛形态大小与配色、"
        f"配色分布、花纹图案、耳朵形状与细节精细度，不做任何风格改动；{subject_extra}"
    )
    pose_section = (
        "构图与姿态：画面最下方约 10% 高度为横向贯穿整个画面的纯黑色色块（#000000），边缘平直整齐。"
        "动物位于画面正中央，只露出头部、颈部和少量胸部，两只前爪自然对称地搭在纯黑色色块的上沿，"
        "身体其余部分隐藏在纯黑色色块后方。动物正视镜头，头部端正，不歪头、不侧身；"
        f"鼻尖、双眼中心与画面竖直中轴线对齐，整体呈现自然的左右对称感。{expression}"
    )
    scene_section = (
        f"场景背景与全局风格统一：背景为干净、均匀的 {bg} 纯色背景，通透不杂乱，"
        "铺满画面最下方纯黑色色块上方的全部背景区域；"
        f"{bg} 背景以及整体明暗光线必须 100% 沿用 <Picture 1> 原有的视觉风格、清晰度、材质纹理、"
        f"轮廓特征与色彩饱和度来呈现，无抠图边缘或风格割裂感，使{blend_subject}与 {bg} 背景自然融为一体，"
        "全图如同原生于 <Picture 1> 的同一幅完整作品。"
    )

    sections = [header, subject_section, pose_section]
    if accessory_section:
        sections.append(accessory_section)
    sections.extend([scene_section, cleanup])
    return "\n\n".join(sections)


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
