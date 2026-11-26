#!/usr/bin/env python3
"""文件用途：生成公共 3 秒先导/7 秒追逐循环过场视频，并规整猫狗三热区样例资产及清单。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ASSETS_DIR.parent.parent
ALGO_VIDEOS_DIR = REPO_ROOT / "algorithm-lab" / "data" / "jobs" / "videos"
DEFAULT_WALLPAPER_DIR = ASSETS_DIR / "default-wallpaper"

WIDTH = 1920
HEIGHT = 1080
FPS = 24

SOURCE_MAP = {
    "cat": {
        "upload_name": "cat-orange-portrait.jpg",
        "actions": {
            "left": ALGO_VIDEOS_DIR / "373de869ef4f44e085e15e937462a69a" / "video-v1.mp4",
            "center": ALGO_VIDEOS_DIR / "0d502cebd0664028b0980a169aface5f" / "video-v1.mp4",
            "right": ALGO_VIDEOS_DIR / "0a15f3b35cfb4ccfaa84ffa5ea664a2e" / "video-v1.mp4",
        },
        "upload_source": ALGO_VIDEOS_DIR / "373de869ef4f44e085e15e937462a69a" / "first.jpg",
    },
    "dog": {
        "upload_name": "dog-labrador-portrait.jpg",
        "actions": {
            "left": ALGO_VIDEOS_DIR / "5c006f5971fa462da4775ce768ad163f" / "video-v1.mp4",
            "center": ALGO_VIDEOS_DIR / "4467c7bd9c40421fa5af3fc5b136a41e" / "video-v1.mp4",
            "right": ALGO_VIDEOS_DIR / "c75369061dea4ede896d0a91429cf14b" / "video-v1.mp4",
        },
        "upload_source": ALGO_VIDEOS_DIR / "5c006f5971fa462da4775ce768ad163f" / "first.png",
    },
}


def probe_video(path: Path) -> dict:
    """使用 ffprobe 实测视频分辨率、宽高比、平均帧率、时长与文件大小。"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,duration,sample_aspect_ratio:format=duration",
        "-of",
        "json",
        str(path),
    ]
    out = subprocess.check_output(cmd)
    data = json.loads(out)
    stream = data["streams"][0]
    w = int(stream["width"])
    h = int(stream["height"])
    fps_frac = Fraction(stream["avg_frame_rate"])
    sar = stream.get("sample_aspect_ratio", "N/A")
    pixel_ratio = Fraction(sar.replace(":", "/")) if sar not in {"N/A", "0:1"} else Fraction(1)
    ratio = Fraction(w, h) * pixel_ratio
    dur_raw = stream.get("duration", "N/A")
    if dur_raw == "N/A":
        dur_raw = data.get("format", {}).get("duration", 0)
    return {
        "format": "mp4",
        "mime": "video/mp4",
        "width": w,
        "height": h,
        "fps": round(float(fps_frac), 3),
        "duration": round(float(dur_raw), 3),
        "aspect_ratio": f"{ratio.numerator}:{ratio.denominator}",
        "size_bytes": path.stat().st_size,
    }


def probe_image(path: Path) -> dict:
    """读取图片分辨率与格式元数据。"""
    with Image.open(path) as img:
        w, h = img.size
        fmt = (img.format or "JPEG").lower()
    return {
        "format": "jpeg" if fmt == "jpeg" else fmt,
        "mime": "image/png" if fmt == "png" else "image/jpeg",
        "width": w,
        "height": h,
        "size_bytes": path.stat().st_size,
    }


def _create_backdrop() -> Image.Image:
    """绘制 2/3 蓝天白云与 1/3 开阔绿地背景底板（1920x1080）。"""
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    horizon_y = 720  # 恰好占画面上方三分之二蓝天、下方三分之一绿地

    # 蓝天渐变
    for y in range(horizon_y):
        t = y / horizon_y
        r = int(86 + (196 - 86) * (t**0.85))
        g = int(162 + (229 - 162) * (t**0.85))
        b = int(235 + (250 - 235) * (t**0.85))
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # 远山柔和剪影增加景深
    hills = [
        (0, 720),
        (0, 668),
        (260, 622),
        (540, 650),
        (880, 608),
        (1240, 646),
        (1580, 616),
        (1920, 654),
        (1920, 720),
    ]
    draw.polygon(hills, fill=(171, 206, 224))

    # 开阔绿地渐变
    for y in range(horizon_y, HEIGHT):
        t = (y - horizon_y) / (HEIGHT - horizon_y)
        r = int(146 - (146 - 92) * t)
        g = int(202 - (202 - 158) * t)
        b = int(112 - (112 - 70) * t)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))

    # 柔和白云层
    cloud_layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(cloud_layer)
    clouds = [
        (260, 175, 1.15),
        (880, 125, 1.35),
        (1480, 210, 1.05),
        (540, 340, 0.85),
        (1220, 360, 0.9),
    ]
    for cx, cy, s in clouds:
        puffs = [
            (-90, 14, 72, 46),
            (-25, -18, 86, 56),
            (55, -8, 76, 50),
            (115, 18, 60, 38),
            (0, 24, 155, 40),
        ]
        for dx, dy, rx, ry in puffs:
            x0, y0 = int(cx + (dx - rx) * s), int(cy + (dy - ry) * s)
            x1, y1 = int(cx + (dx + rx) * s), int(cy + (dy + ry) * s)
            cdraw.ellipse([x0, y0, x1, y1], fill=(255, 255, 255, 210))
    cloud_layer = cloud_layer.filter(ImageFilter.GaussianBlur(radius=6))
    img = Image.alpha_composite(img.convert("RGBA"), cloud_layer).convert("RGB")
    return img


def _draw_ground_motion(draw: ImageDraw.ImageDraw, offset_px: float) -> None:
    """绘制与循环周期对齐的草地纹理块与透视光斑。"""
    tile_w = 320
    shift = offset_px % tile_w
    for row, (y, scale, color) in enumerate(
        [
            (748, 0.7, (130, 188, 96)),
            (815, 0.9, (116, 178, 84)),
            (895, 1.15, (101, 164, 72)),
            (985, 1.35, (86, 148, 61)),
        ]
    ):
        for col in range(-1, WIDTH // tile_w + 3):
            x = col * tile_w - shift + (row * 95) % tile_w
            w = int(68 * scale)
            h = int(12 * scale)
            draw.ellipse([x, y, x + w, y + h], fill=color)


def _draw_running_cat(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    gait_phase: float,
    scale: float = 1.0,
) -> None:
    """绘制面向右侧奔跑的橘白猫（带交替步态和飘动尾巴）。"""
    bounce = -math.sin(gait_phase * 2) * 10 * scale
    y = cy + bounce
    s = scale

    # 地面投影
    shadow_rx = (76 - 10 * math.sin(gait_phase * 2)) * s
    draw.ellipse(
        [cx - shadow_rx, cy + 58 * s, cx + shadow_rx, cy + 78 * s],
        fill=(72, 122, 54),
    )

    # 后腿 & 前腿交替伸展
    stride_a = math.sin(gait_phase)
    stride_b = math.sin(gait_phase + math.pi)
    legs = [
        # (肩/臀x偏移, y偏移, 摆幅, 颜色)
        (-48, 22, stride_b * 34, (214, 125, 48)),
        (46, 22, stride_a * 36, (214, 125, 48)),
        (-40, 26, stride_a * 38, (242, 158, 76)),
        (52, 26, stride_b * 36, (242, 158, 76)),
    ]
    for lx, ly, swing, col in legs:
        x0, y0 = cx + lx * s, y + ly * s
        x1 = x0 + swing * s
        y1 = y0 + (34 - abs(swing) * 0.25) * s
        draw.line([(x0, y0), (x1, y1)], fill=col, width=int(18 * s))
        draw.ellipse([x1 - 11 * s, y1 - 8 * s, x1 + 11 * s, y1 + 8 * s], fill=(252, 245, 238))

    # 尾巴波浪
    tail_wave = math.sin(gait_phase + 0.6) * 18 * s
    tail_pts = [
        (cx - 64 * s, y - 4 * s),
        (cx - 105 * s, y - 28 * s + tail_wave * 0.5),
        (cx - 134 * s, y - 42 * s + tail_wave),
    ]
    draw.line(tail_pts, fill=(235, 140, 56), width=int(17 * s), joint="curve")
    draw.ellipse(
        [
            tail_pts[-1][0] - 9 * s,
            tail_pts[-1][1] - 9 * s,
            tail_pts[-1][0] + 9 * s,
            tail_pts[-1][1] + 9 * s,
        ],
        fill=(252, 245, 238),
    )

    # 躯干与白胸毛
    draw.ellipse([cx - 72 * s, y - 34 * s, cx + 68 * s, y + 38 * s], fill=(241, 152, 68))
    draw.ellipse([cx - 38 * s, y + 6 * s, cx + 62 * s, y + 36 * s], fill=(252, 247, 240))
    # 虎斑条纹
    for bx in (-34, -8, 18):
        draw.arc(
            [cx + (bx - 12) * s, y - 34 * s, cx + (bx + 12) * s, y + 2 * s],
            start=200,
            end=340,
            fill=(196, 102, 34),
            width=max(2, int(6 * s)),
        )

    # 头部与耳朵
    hx, hy = cx + 68 * s, y - 32 * s
    # 左耳(后)、右耳(前)
    draw.polygon(
        [(hx - 14 * s, hy - 22 * s), (hx - 4 * s, hy - 66 * s), (hx + 16 * s, hy - 30 * s)],
        fill=(235, 140, 56),
    )
    draw.polygon(
        [(hx + 4 * s, hy - 26 * s), (hx + 24 * s, hy - 64 * s), (hx + 34 * s, hy - 20 * s)],
        fill=(245, 165, 86),
    )
    draw.polygon(
        [(hx + 9 * s, hy - 28 * s), (hx + 22 * s, hy - 54 * s), (hx + 29 * s, hy - 24 * s)],
        fill=(248, 198, 198),
    )
    draw.ellipse([hx - 36 * s, hy - 34 * s, hx + 44 * s, hy + 34 * s], fill=(244, 158, 76))
    draw.ellipse([hx + 4 * s, hy - 4 * s, hx + 44 * s, hy + 32 * s], fill=(253, 248, 242))
    # 眼睛与粉鼻
    draw.ellipse([hx + 12 * s, hy - 14 * s, hx + 26 * s, hy], fill=(38, 32, 28))
    draw.ellipse([hx + 16 * s, hy - 12 * s, hx + 21 * s, hy - 7 * s], fill=(255, 255, 255))
    draw.polygon(
        [(hx + 38 * s, hy + 4 * s), (hx + 45 * s, hy + 9 * s), (hx + 36 * s, hy + 13 * s)],
        fill=(242, 134, 148),
    )


def _draw_running_dog(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    gait_phase: float,
    scale: float = 1.0,
) -> None:
    """绘制面向右侧欢快奔跑的浅金狗狗（带垂耳、吐舌与摇尾）。"""
    bounce = -math.sin(gait_phase * 2) * 12 * scale
    y = cy + bounce
    s = scale

    # 地面投影
    shadow_rx = (92 - 12 * math.sin(gait_phase * 2)) * s
    draw.ellipse(
        [cx - shadow_rx, cy + 68 * s, cx + shadow_rx, cy + 92 * s],
        fill=(68, 118, 52),
    )

    stride_a = math.sin(gait_phase)
    stride_b = math.sin(gait_phase + math.pi)
    legs = [
        (-58, 26, stride_b * 40, (214, 174, 108)),
        (56, 26, stride_a * 42, (214, 174, 108)),
        (-48, 30, stride_a * 42, (242, 206, 146)),
        (64, 30, stride_b * 40, (242, 206, 146)),
    ]
    for lx, ly, swing, col in legs:
        x0, y0 = cx + lx * s, y + ly * s
        x1 = x0 + swing * s
        y1 = y0 + (42 - abs(swing) * 0.25) * s
        draw.line([(x0, y0), (x1, y1)], fill=col, width=int(22 * s))
        draw.ellipse([x1 - 12 * s, y1 - 8 * s, x1 + 14 * s, y1 + 9 * s], fill=(250, 240, 224))

    # 摇摆短尾
    tail_wave = math.sin(gait_phase * 2.0) * 16 * s
    draw.line(
        [(cx - 78 * s, y - 14 * s), (cx - 118 * s, y - 48 * s + tail_wave)],
        fill=(236, 194, 128),
        width=int(20 * s),
    )

    # 躯干与项圈
    draw.ellipse([cx - 88 * s, y - 40 * s, cx + 82 * s, y + 44 * s], fill=(244, 210, 152))
    draw.ellipse([cx - 42 * s, y + 4 * s, cx + 76 * s, y + 42 * s], fill=(252, 244, 228))
    draw.line([(cx + 50 * s, y - 30 * s), (cx + 76 * s, y + 20 * s)], fill=(219, 88, 72), width=int(12 * s))

    # 头部、口吻、吐舌、垂耳
    hx, hy = cx + 84 * s, y - 40 * s
    draw.ellipse([hx - 44 * s, hy - 38 * s, hx + 46 * s, hy + 38 * s], fill=(246, 214, 158))
    # 吻部与粉色小舌头
    draw.ellipse([hx + 18 * s, hy - 8 * s, hx + 66 * s, hy + 28 * s], fill=(252, 242, 224))
    draw.ellipse(
        [hx + 34 * s, hy + 20 * s, hx + 52 * s, hy + (38 + 4 * math.sin(gait_phase)) * s],
        fill=(242, 124, 138),
    )
    # 黑鼻头
    draw.ellipse([hx + 54 * s, hy - 6 * s, hx + 68 * s, hy + 7 * s], fill=(42, 32, 28))
    # 眼睛
    draw.ellipse([hx + 14 * s, hy - 18 * s, hx + 28 * s, hy - 4 * s], fill=(38, 28, 22))
    draw.ellipse([hx + 18 * s, hy - 16 * s, hx + 22 * s, hy - 12 * s], fill=(255, 255, 255))
    # 垂耳随奔跑微扬
    ear_lift = math.sin(gait_phase) * 8 * s
    draw.polygon(
        [
            (hx - 14 * s, hy - 22 * s),
            (hx - 46 * s, hy + 18 * s - ear_lift),
            (hx - 16 * s, hy + 26 * s - ear_lift),
            (hx + 6 * s, hy - 6 * s),
        ],
        fill=(216, 170, 102),
    )


def _encode_frames_ffmpeg(frames: list[Image.Image], output_path: Path, crf: int = 20) -> None:
    """将 RGB 帧序列通过管道编码为无音轨、零 B 帧、前置 moov 的 1920x1080 24fps H.264 MP4。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(crf),
        "-bf",
        "0",
        "-g",
        str(FPS),
        "-keyint_min",
        str(FPS),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(tmp_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"ffmpeg 编码失败 ({code}): {stderr}")
        tmp_path.replace(output_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _loop_state(u: float) -> tuple[float, float, float, float, float]:
    """根据循环归一化进度 u in [0, 1) 返回猫/狗 x 坐标、步态相位与地面偏移。"""
    # u=0: 猫在前(1100), 狗在后(760)
    # u≈0.43 (3s): 狗超过猫在前(1180), 猫在后(740)
    # u=1.0: 回到 猫(1100), 狗(760)，周期函数保证首尾坐标/速度/步态精确对齐
    cat_x = 920.0 + 180.0 * math.cos(2 * math.pi * u)
    dog_x = 970.0 - 210.0 * math.cos(2 * math.pi * u)
    # 7 秒共 14 个完整步态周期（每秒 2 步）
    cat_phase = 2 * math.pi * 14 * u
    dog_phase = 2 * math.pi * 14 * u + math.pi * 0.7
    # 7 秒草地平移距离为 320px 周期的整数倍（14 * 320 = 4480px）
    ground_offset = 14.0 * 320.0 * u
    return cat_x, dog_x, cat_phase, dog_phase, ground_offset


def _fragmented_avc_codec(data: bytes) -> str | None:
    """从分片 MP4 的初始化段提取 AVC 编码标识，普通 MP4 返回 None。"""
    codec = None
    offset = 0
    while offset + 8 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + size
        if size < 8 or end > len(data):
            return None
        kind = data[offset + 4:offset + 8]
        if kind == b"moov":
            avcc = data.find(b"avcC\x01", offset + 8, end)
            if avcc >= 0 and avcc + 8 <= end:
                codec = f"avc1.{data[avcc + 5:avcc + 8].hex()}"
        if kind == b"moof":
            return codec
        offset = end
    return None


def _transition_metadata(intro_path: Path, loop_path: Path) -> dict[str, dict]:
    """返回过场规格、缓存版本及支持连续播放时的编码标识。"""
    transitions = {}
    for name, path in (("intro", intro_path), ("loop", loop_path)):
        data = path.read_bytes()
        info = {
            "path": f"transitions/{path.name}",
            **probe_video(path),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        codec = _fragmented_avc_codec(data)
        if codec:
            info["mse_codec"] = codec
        transitions[name] = info
    return transitions


def build_transitions(force_synthetic: bool = False) -> dict[str, dict]:
    """探测或重建 3 秒先导（intro-3s.mp4）和 7 秒追逐循环（chase-loop-7s.mp4）。"""
    trans_dir = ASSETS_DIR / "transitions"
    trans_dir.mkdir(parents=True, exist_ok=True)
    intro_path = trans_dir / "intro-3s.mp4"
    loop_path = trans_dir / "chase-loop-7s.mp4"

    if not force_synthetic and intro_path.is_file() and loop_path.is_file():
        return _transition_metadata(intro_path, loop_path)

    backdrop = _create_backdrop()

    # 1) 7 秒追逐循环 (168 帧)
    loop_frames: list[Image.Image] = []
    for idx in range(FPS * 7):
        u = idx / (FPS * 7)
        cat_x, dog_x, cat_phase, dog_phase, ground_offset = _loop_state(u)
        frame = backdrop.copy()
        draw = ImageDraw.Draw(frame)
        _draw_ground_motion(draw, ground_offset)
        # 远侧跑道(y=758)与近侧跑道(y=835)错开，超车时不重叠遮挡
        _draw_running_dog(draw, dog_x, 762, dog_phase, scale=0.92)
        _draw_running_cat(draw, cat_x, 838, cat_phase, scale=1.0)
        loop_frames.append(frame)

    _encode_frames_ffmpeg(loop_frames, loop_path)

    # 2) 3 秒入场先导 (72 帧)，末尾直接对齐 loop 第 0 帧状态
    target_cat_x, target_dog_x, target_cat_phase, target_dog_phase, target_ground = _loop_state(0.0)
    intro_frames: list[Image.Image] = []
    total_intro = FPS * 3
    for idx in range(total_intro):
        # 令 v=1 对应第 72 帧时刻（即追逐循环第 0 帧）
        v = (idx + 1) / total_intro
        ease_cat = 1 - (1 - v) ** 1.45
        cat_x = -180.0 + (target_cat_x + 180.0) * ease_cat
        # 狗比猫延迟 0.5 秒从左侧画外跟上
        v_dog = max(0.0, (v - 0.16) / 0.84)
        ease_dog = 1 - (1 - v_dog) ** 1.25
        dog_x = -260.0 + (target_dog_x + 260.0) * ease_dog

        # 从末尾精确倒推整数个步态周期，确保切到 loop 第 0 帧相位连续
        steps_left = (total_intro - 1 - idx) / FPS * 2.0
        cat_phase = target_cat_phase - 2 * math.pi * steps_left
        dog_phase = target_dog_phase - 2 * math.pi * steps_left
        ground_offset = target_ground - (total_intro - 1 - idx) / FPS * 640.0

        frame = backdrop.copy()
        draw = ImageDraw.Draw(frame)
        _draw_ground_motion(draw, ground_offset)
        if dog_x > -240:
            _draw_running_dog(draw, dog_x, 762, dog_phase, scale=0.92)
        _draw_running_cat(draw, cat_x, 838, cat_phase, scale=1.0)
        intro_frames.append(frame)

    _encode_frames_ffmpeg(intro_frames, intro_path)

    return _transition_metadata(intro_path, loop_path)


def _normalize_video_1080p(src: Path, dst: Path) -> None:
    """将源视频统一转为无音轨、零 B 帧、前置 moov 的 1920x1080 24fps H.264 MP4。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=24",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "19",
        "-bf",
        "0",
        "-g",
        str(FPS),
        "-keyint_min",
        str(FPS),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)


def _smooth_loop_and_optimize_video(path: Path, blend_tail_frames: int = 0) -> None:
    """就地优化已有 MP4：剥离音轨、禁用 B 帧、固定关键帧并前置 moov，可选首尾平滑过渡。"""
    if blend_tail_frames <= 0:
        _normalize_video_1080p(path, path)
        return

    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=24",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
    )
    frame_size = WIDTH * HEIGHT * 3
    total = len(raw) // frame_size
    if total <= blend_tail_frames + 1:
        _normalize_video_1080p(path, path)
        return

    frames = [
        Image.frombytes("RGB", (WIDTH, HEIGHT), raw[i * frame_size : (i + 1) * frame_size])
        for i in range(total)
    ]
    first = frames[0]
    tail_start = total - blend_tail_frames
    for idx in range(blend_tail_frames):
        alpha = (idx + 1) / (blend_tail_frames + 1)
        frames[tail_start + idx] = Image.blend(frames[tail_start + idx], first, alpha)

    tmp_path = path.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{WIDTH}x{HEIGHT}",
        "-r",
        str(FPS),
        "-i",
        "-",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-bf",
        "0",
        "-g",
        str(FPS),
        "-keyint_min",
        str(FPS),
        "-sc_threshold",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-an",
        str(tmp_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        stderr = proc.stderr.read().decode("utf-8", errors="ignore") if proc.stderr else ""
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg 平滑循环编码失败: {stderr}")
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _build_fallback_action_video(species: str, direction: str, dst: Path) -> None:
    """当环境无本地实验视频时生成 4 秒 1920x1080 24fps 占位互动视频。"""
    frames: list[Image.Image] = []
    total = FPS * 4
    target_x = {"left": int(WIDTH * 0.17), "center": int(WIDTH * 0.50), "right": int(WIDTH * 0.83)}[direction]
    bg_color = (42, 54, 66) if species == "cat" else (62, 68, 76)
    pet_color = (232, 152, 82) if species == "cat" else (240, 214, 162)

    for idx in range(total):
        t = idx / (total - 1)
        reach = math.sin(math.pi * max(0.0, min(1.0, (t - 0.12) / 0.76)))
        img = Image.new("RGB", (WIDTH, HEIGHT), bg_color)
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 740, WIDTH, HEIGHT], fill=(56, 66, 78))
        cx, cy = WIDTH // 2, 620
        draw.ellipse([cx - 260, cy - 120, cx + 260, cy + 200], fill=pet_color)
        draw.ellipse([cx - 170, cy - 290, cx + 170, cy - 10], fill=pet_color)
        if reach > 0.01:
            px = int(cx + (target_x - cx) * reach)
            py = int(680 - 180 * reach)
            draw.line([(cx, 680), (px, py)], fill=(252, 244, 232), width=36)
            draw.ellipse([px - 48, py - 48, px + 48, py + 48], fill=(248, 178, 184))
        frames.append(img)
    _encode_frames_ffmpeg(frames, dst)


def _extract_first_frame(video_path: Path, image_path: Path) -> None:
    """从视频第 1 帧提取高质量 JPEG 静帧。"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(image_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def build_default_wallpaper() -> dict | None:
    """探测默认壁纸资产（动态待机 + 三热区交互），必要时自动提取静态首帧。"""
    idle_vid = DEFAULT_WALLPAPER_DIR / "idle.mp4"
    action_files = {slot: DEFAULT_WALLPAPER_DIR / f"{slot}.mp4" for slot in ("left", "center", "right")}
    if not idle_vid.is_file() or not all(path.is_file() for path in action_files.values()):
        return None

    idle_img = DEFAULT_WALLPAPER_DIR / "idle.jpg"
    if not idle_img.is_file():
        _extract_first_frame(idle_vid, idle_img)

    return {
        "species": "dog",
        "name": "默认狗狗",
        "gender": "未设置",
        "breed": "默认壁纸",
        "idle_image": {"path": "default-wallpaper/idle.jpg", **probe_image(idle_img)},
        "idle_video": {"path": "default-wallpaper/idle.mp4", **probe_video(idle_vid)},
        "actions": {
            slot: {"path": f"default-wallpaper/{slot}.mp4", **probe_video(path)}
            for slot, path in action_files.items()
        },
    }


def build_samples(force_rebuild: bool = False, existing_manifest: dict | None = None) -> dict[str, dict]:
    """规整或探测猫狗三方向样例素材，并提取一致首帧作为 idle.jpg。"""
    samples_info: dict[str, dict] = {}
    existing_samples = (existing_manifest or {}).get("samples", {})
    for species, spec in SOURCE_MAP.items():
        sample_dir = ASSETS_DIR / "samples" / species
        sample_dir.mkdir(parents=True, exist_ok=True)
        idle_path = sample_dir / "idle.jpg"
        upload_path = sample_dir / "sample-upload.jpg"
        existing_species = existing_samples.get(species, {})
        existing_actions = existing_species.get("actions", {})

        has_all_archived = (
            idle_path.is_file()
            and upload_path.is_file()
            and all((sample_dir / f"{direction}.mp4").is_file() for direction in spec["actions"])
        )
        has_any_algo_source = any(src.is_file() for src in spec["actions"].values())

        if not force_rebuild and has_all_archived and not has_any_algo_source:
            actions_meta = {}
            for direction in spec["actions"]:
                dst_video = sample_dir / f"{direction}.mp4"
                origin = existing_actions.get(direction, {}).get("origin", "archived")
                actions_meta[direction] = {
                    "path": f"samples/{species}/{direction}.mp4",
                    "origin": origin,
                    **probe_video(dst_video),
                }
            samples_info[species] = {
                "idle_image": {"path": f"samples/{species}/idle.jpg", **probe_image(idle_path)},
                "sample_upload": {"path": f"samples/{species}/sample-upload.jpg", **probe_image(upload_path)},
                "actions": actions_meta,
            }
            continue

        actions_meta = {}
        for direction, src_video in spec["actions"].items():
            dst_video = sample_dir / f"{direction}.mp4"
            if src_video.is_file() and (force_rebuild or not dst_video.is_file()):
                _normalize_video_1080p(src_video, dst_video)
                origin = f"algorithm-lab:{src_video.parent.name}"
            elif not dst_video.is_file():
                _build_fallback_action_video(species, direction, dst_video)
                origin = "synthetic-fallback"
            else:
                origin = existing_actions.get(direction, {}).get(
                    "origin", f"algorithm-lab:{src_video.parent.name}" if src_video.is_file() else "archived"
                )
            actions_meta[direction] = {
                "path": f"samples/{species}/{direction}.mp4",
                "origin": origin,
                **probe_video(dst_video),
            }

        # 从规整后 left.mp4 第 1 帧提取待机图，保证像素级首尾无缝衔接
        if force_rebuild or not idle_path.is_file():
            _extract_first_frame(sample_dir / "left.mp4", idle_path)

        # 生成示例上传照片（供演示快捷填充上传表单）
        upload_src = spec["upload_source"]
        if force_rebuild or not upload_path.is_file():
            if upload_src.is_file():
                with Image.open(upload_src) as im:
                    im.convert("RGB").save(upload_path, format="JPEG", quality=92)
            else:
                shutil.copyfile(idle_path, upload_path)

        samples_info[species] = {
            "idle_image": {"path": f"samples/{species}/idle.jpg", **probe_image(idle_path)},
            "sample_upload": {"path": f"samples/{species}/sample-upload.jpg", **probe_image(upload_path)},
            "actions": actions_meta,
        }
    return samples_info


def optimize_all_existing_videos() -> None:
    """重编码目录内全部 MP4（含过场、默认壁纸与猫狗样例），并对待机循环做首尾平滑。"""
    idle_vid = DEFAULT_WALLPAPER_DIR / "idle.mp4"
    if idle_vid.is_file():
        _smooth_loop_and_optimize_video(idle_vid, blend_tail_frames=8)

    for slot in ("left", "center", "right"):
        p = DEFAULT_WALLPAPER_DIR / f"{slot}.mp4"
        if p.is_file():
            _smooth_loop_and_optimize_video(p, blend_tail_frames=0)

    for species in ("cat", "dog"):
        for slot in ("left", "center", "right"):
            p = ASSETS_DIR / "samples" / species / f"{slot}.mp4"
            if p.is_file():
                _smooth_loop_and_optimize_video(p, blend_tail_frames=0)

    for name in ("intro-3s.mp4", "chase-loop-7s.mp4"):
        p = ASSETS_DIR / "transitions" / name
        if p.is_file():
            _smooth_loop_and_optimize_video(p, blend_tail_frames=0)


def main() -> None:
    parser = argparse.ArgumentParser(description="探测或重建网页 Demo 公共素材并更新 manifest.json")
    parser.add_argument("--rebuild-transitions", action="store_true", help="重新生成合成过场视频并覆盖现有文件")
    parser.add_argument("--rebuild-samples", action="store_true", help="强制重建猫狗样例视频与图片")
    parser.add_argument("--optimize-videos", action="store_true", help="优化全部现有 MP4 的关键帧/B帧/音轨与循环连续性")
    args = parser.parse_args()

    if args.optimize_videos:
        optimize_all_existing_videos()

    manifest_path = ASSETS_DIR / "manifest.json"
    existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}

    transitions = build_transitions(force_synthetic=args.rebuild_transitions)
    default_wallpaper = build_default_wallpaper()
    samples = build_samples(force_rebuild=args.rebuild_samples, existing_manifest=existing_manifest)
    manifest: dict = {
        "version": "1.0.0",
        "target_spec": {"width": WIDTH, "height": HEIGHT, "aspect_ratio": "16:9", "fps": FPS},
        "transitions": transitions,
    }
    if default_wallpaper is not None:
        manifest["default_wallpaper"] = default_wallpaper
    manifest["samples"] = samples
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {manifest_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
