"""文件用途：定义车机 PRD 的待机图、过场关键帧和动作视频生成预设。"""

from .video import VideoOptions

DEFAULT_BACKGROUND = "暖米色影棚，简洁哑光地面与柔和自然光"


def idle_prompt(pet: str) -> str:
    """构造待机提示词。参数 pet 为物种名称，返回含默认背景的完整提示词。"""
    return (
        f"以参考图里的{pet}作为唯一主体，准确保留它的品种感、脸型、眼睛、毛色花纹和体型。"
        "把原照转换成一张写实宠物壁纸。宠物正面自然趴卧，抬头直视镜头，双前爪清晰向前伸展，头与身体保持居中。"
        "横向16:9，固定平视中景，完整身体约占画面宽度60%，左右为伸爪或探头留出空间。"
        f"背景：{DEFAULT_BACKGROUND}。"
        "细节清晰。只出现一只宠物，无文字、标记、水印或多余肢体。"
    )


_CHASE_SCENE = (
    "参考图1（<<<image_1>>>）是猫，参考图2（<<<image_2>>>）是狗，保持两者各自的脸型、毛色和花纹。"
    "若另有场景参考图，仅复用该图的场景、机位、比例和光照。"
    "生成16:9单张半写实过场关键帧。固定侧面中远景，画面上方约三分之二为蓝天白云，"
    "下方约三分之一为简洁开阔绿地。角色面向屏幕右侧，身体完整、奔跑姿态有四肢支撑或腾空的动势。"
    "光线柔和，无文字、水印、分割线或多格分镜。"
)


def chase_keyframe(label: str, placement: str) -> dict:
    """构造追逐关键帧预设。参数为素材名称与角色位置，返回页面所需配置。"""
    return {"label": label, "min_photos": 2, "max_photos": 3, "prompt": f"{_CHASE_SCENE}{placement}"}


IMAGE_PRESETS = {
    "cat-idle": {"label": "猫咪待机图", "min_photos": 1, "max_photos": 1, "prompt": idle_prompt("猫咪")},
    "dog-idle": {"label": "狗狗待机图", "min_photos": 1, "max_photos": 1, "prompt": idle_prompt("狗狗")},
    "chase-entry": chase_keyframe(
        "追逐 · 入场起始帧", "猫刚从画面左侧进入，位于左侧，正在向中央跑。狗此刻在左侧画外，即将跟上。画面中暂时只出现猫。"
    ),
    "chase-pair": chase_keyframe(
        "追逐 · 猫前狗后关键帧", "猫在画面中部偏右，狗在中部偏左，两只宠物朝右连续跑，如正处于同一次追逐。"
    ),
    "chase-cat": chase_keyframe(
        "切换 · 猫居中关键帧", "只出现一只朝右持续奔跑的猫，猫位于画面正中央，左侧预留狗的入场空间。"
    ),
    "chase-dog": chase_keyframe(
        "切换 · 狗居中关键帧", "只出现一只朝右持续奔跑的狗，狗位于画面正中央，左侧预留猫的入场空间。"
    ),
}

# 方向和参考中心均以观众看屏幕的视角定义。
_TARGETS = {
    "left": ("左", "画面左区中心（距左边约17%）", "右前爪"),
    "center": ("中", "画面正中央（距左边约50%）", "左前爪"),
    "right": ("右", "画面右区中心（距左边约83%）", "左前爪"),
}
_LOCK_VIEW = (
    "16:9横屏，固定机位、焦距、构图、背景与光照。只保留原宠物，维持它的脸、花纹和体型；"
    "身体保持正面居中趴卧。全程无相机移动、切镜、文字、光圈标记或多余肢体。"
)
_CHASE_VIDEO = (
    "横向16:9，固定侧面镜头，保留参考帧中的蓝天白云和绿地。"
    "两只动物各自保持原有外观，朝画面右侧连续奔跑，有清晰交替步态和自然落地。"
    "通过角色相对移动表现追赶，保持各自轮廓可辨，避免重叠变形。无镜头运动、切镜、标记或文字。"
)


def video_preset(label: str, prompt: str, seconds: int, first: str, tail: str | None = None) -> dict:
    """生成视频预设。参数为名称、提示词、秒数和建议关键帧，返回页面可加载的规格。"""
    return {
        "label": label,
        "prompt": prompt,
        "options": VideoOptions(duration=seconds).model_dump(),
        "first_hint": first,
        "tail_hint": tail,
        "target_fps": 24,  # 可灵现有接口不下发帧率，按成品实测验收。
    }


def action_presets(species: str) -> dict[str, dict]:
    """生成某个物种的三方向动作。参数为 cat 或 dog，返回按画面方向索引的预设。"""
    is_cat = species == "cat"
    pet = "猫咪" if is_cat else "狗狗"
    result = {}
    for direction, (name, target, paw) in _TARGETS.items():
        if is_cat:
            motion = (
                f"0–0.5秒从待机姿态开始。0.5–1.7秒抬起并伸出猫自身的{paw}，"
                f"让可见肉垫朝镜头，明显伸向{target}。另一只爪留在原地支撑。"
                "1.7–2.2秒用肉垫轻触并短暂停留。2.2–3.6秒同一只爪自然沿原路径收回。"
                "3.6–4秒停在与开头相同的趴卧姿势。"
            )
        else:
            mouth = "保持自然微张嘴" if direction == "center" else "自然收起舌头"
            motion = (
                "0–0.5秒为待机姿态。0.5–1.2秒迅速抬头，微微吐舌并自然摇尾，双前爪留在地面。"
                f"1.2–2.1秒{mouth}，沿{target}明显向镜头探头，以鼻尖轻轻向上顶触。"
                "2.1–3.6秒收回脑袋，回到原来正面趴卧的位置与表情。3.6–4秒保持与开头一致。"
            )
        word = "伸爪" if is_cat else "鼻尖轻触"
        result[f"{species}-{direction}"] = video_preset(f"{name}热区 · {word}", _LOCK_VIEW + motion, 4, f"{pet}待机图")
    return result


VIDEO_PRESETS = {
    "猫咪": action_presets("cat"),
    "狗狗": action_presets("dog"),
    "追逐过场": {
        "chase-intro": video_preset(
            "首次录入 · 先导", _CHASE_VIDEO +
            "猫先由左侧跑到画面中部偏右，狗稍后从左边入画跟上；保持固定相机。"
            "最后一帧猫在前、狗在后，保持自然奔跑相位，接入等待循环。",
            3, "入场起始帧", "猫前狗后关键帧",
        ),
        "chase-loop": video_preset(
            "首次录入 · 等待循环", _CHASE_VIDEO +
            "0–1秒猫前狗后，随后狗加速从猫旁追上，在第3秒左右到达猫前方。"
            "猫再加速超过狗；第6–7秒恢复猫前狗后的初始位置。最后一帧与第一帧的"
            "位置、画面构图与步态相位一致，结尾继续奔跑，以便循环。",
            7, "猫前狗后关键帧",
        ),
        "cat-to-dog": video_preset(
            "跨种切换 · 猫切狗", _CHASE_VIDEO +
            "猫在中央奔跑。狗从画面左侧进入追上猫，在另一条跑道相对向前超过猫，最后保持奔跑并占据中央。"
            "猫相对向左移并完全退出画面。",
            3, "猫居中关键帧", "狗居中关键帧",
        ),
        "dog-to-cat": video_preset(
            "跨种切换 · 狗切猫", _CHASE_VIDEO +
            "狗在中央奔跑。猫从画面左侧进入追上狗，在另一条跑道相对向前超过狗，最后保持奔跑并占据中央。"
            "狗相对向左移并完全退出画面。",
            3, "狗居中关键帧", "猫居中关键帧",
        ),
    },
}
VIDEO_PRESET_LOOKUP = {key: spec for group in VIDEO_PRESETS.values() for key, spec in group.items()}
