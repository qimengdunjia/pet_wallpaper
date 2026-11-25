"""文件用途：校验上传照片、探测视频规格并验收待发布的完整宠物资产版本。"""

from __future__ import annotations

import io
import json
import subprocess
import warnings
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000
REQUIRED_ACTION_SLOTS = ("left", "center", "right")


class PhotoValidationError(ValueError):
    """上传照片格式、尺寸或比例不符合要求时抛出。"""


class AssetValidationError(ValueError):
    """待机图或互动视频不完整或规格损坏时抛出。"""


def normalize_photo(content: bytes) -> bytes:
    """校验并规范化上传照片；返回移除 EXIF 元数据的 RGB JPEG 字节。"""
    if not content:
        raise PhotoValidationError("请上传非空图片文件")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise PhotoValidationError("只支持真实编码为 JPEG 或 PNG 的宠物照片")
                source.load()
                image = ImageOps.exif_transpose(source)
                width, height = image.size
                if min(width, height) < 300 or not 0.4 <= width / height <= 2.5:
                    raise PhotoValidationError("照片宽高均需至少 300 像素，且宽高比在 1:2.5 至 2.5:1 之间")
                image.thumbnail((4096, 4096))
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    base = Image.new("RGB", rgba.size, "#eeeeee")
                    base.paste(rgba, mask=rgba.getchannel("A"))
                    image = base
                else:
                    image = image.convert("RGB")
                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=92)
                return buf.getvalue()
    except PhotoValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise PhotoValidationError("无法解析照片，请确认文件未损坏且像素未超限") from exc


def inspect_image(path: Path) -> dict:
    """校验待机图文件并提取分辨率与格式信息。"""
    if not path.is_file():
        raise AssetValidationError(f"待机图文件不存在: {path.name}")
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            width, height = img.size
            fmt = (img.format or "").upper()
        if fmt not in {"JPEG", "PNG"} or width <= 0 or height <= 0:
            raise AssetValidationError("待机图不是有效的 JPEG/PNG 图片")
        return {
            "format": "jpeg" if fmt == "JPEG" else "png",
            "mime": "image/jpeg" if fmt == "JPEG" else "image/png",
            "width": width,
            "height": height,
            "size_bytes": path.stat().st_size,
        }
    except AssetValidationError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise AssetValidationError(f"待机图损坏或不可读: {path.name}") from exc


def inspect_video(path: Path) -> dict:
    """使用 ffprobe 校验并读取视频真实分辨率、宽高比、平均帧率与时长。"""
    if not path.is_file():
        raise AssetValidationError(f"视频文件不存在: {path.name}")
    with path.open("rb") as handle:
        header = handle.read(32)
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise AssetValidationError(f"视频文件 {path.name} 不是有效的 MP4 容器")

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
    try:
        try:
            res = subprocess.run(cmd, check=True, capture_output=True, timeout=15)
        except subprocess.TimeoutExpired:
            # 发布服务器短时繁忙时，给已落盘的视频一次重新探测的机会。
            res = subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        data = json.loads(res.stdout)
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        fps = Fraction(stream["avg_frame_rate"])
        sar = stream.get("sample_aspect_ratio", "N/A")
        pixel_ratio = Fraction(sar.replace(":", "/")) if sar not in {"N/A", "0:1"} else Fraction(1)
        ratio = Fraction(width, height) * pixel_ratio
        duration_raw = stream.get("duration", "N/A")
        if duration_raw == "N/A":
            duration_raw = data.get("format", {}).get("duration")
        duration = float(duration_raw)
        if width <= 0 or height <= 0 or fps <= 0 or duration <= 0:
            raise ValueError("视频维度或时长无效")
    except FileNotFoundError as exc:
        raise AssetValidationError("服务器缺少 ffprobe，无法校验视频规格") from exc
    except subprocess.TimeoutExpired as exc:
        raise AssetValidationError(f"读取视频 {path.name} 的规格超时") from exc
    except (subprocess.SubprocessError, ValueError, ZeroDivisionError, KeyError, IndexError, TypeError) as exc:
        raise AssetValidationError(f"无法读取视频 {path.name} 的规格元数据") from exc

    return {
        "format": "mp4",
        "mime": "video/mp4",
        "width": width,
        "height": height,
        "fps": round(float(fps), 3),
        "duration": round(duration, 3),
        "aspect_ratio": f"{ratio.numerator}:{ratio.denominator}",
        "size_bytes": path.stat().st_size,
    }


def normalize_video_for_playback(path: Path) -> None:
    """规范化生成视频以便无缝播放：剥离音轨、消除 B 帧并确保 moov 前置。"""
    if not path.is_file():
        return
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,has_b_frames",
        "-of",
        "json",
        str(path),
    ]
    try:
        res = subprocess.run(probe_cmd, check=True, capture_output=True, timeout=15)
        streams = json.loads(res.stdout).get("streams", [])
    except (subprocess.SubprocessError, ValueError, KeyError):
        return

    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    has_audio = any(s.get("codec_type") != "video" for s in streams)
    has_b_frames = any(int(s.get("has_b_frames") or 0) > 0 for s in video_streams)
    if video_streams and not has_audio and not has_b_frames:
        return

    tmp = path.with_suffix(".norm.mp4")
    if video_streams and not has_b_frames:
        encode_args = ["-c:v", "copy"]
    else:
        encode_args = [
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "veryfast",
            "-crf",
            "19",
            "-bf",
            "0",
            "-g",
            "24",
            "-keyint_min",
            "24",
            "-sc_threshold",
            "0",
            "-pix_fmt",
            "yuv420p",
        ]

    # 限制解码和编码线程，避免多个版本同时发布时挤占小规格服务器资源。
    cmd = ["ffmpeg", "-y", "-threads", "1", "-i", str(path), *encode_args, "-movflags", "+faststart", "-an", str(tmp)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
        tmp.replace(path)
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    finally:
        tmp.unlink(missing_ok=True)


def validate_asset_bundle(idle_path: Path, action_paths: dict[str, Path]) -> tuple[dict, dict[str, dict]]:
    """检查待机图与三段交互视频，以及供应商提供的待机视频，返回素材元数据。"""
    slots = set(action_paths) - {"idle-video"}
    if slots != set(REQUIRED_ACTION_SLOTS):
        raise AssetValidationError("动作视频缺少左、中或右方向")
    idle_meta = inspect_image(idle_path)
    actions_meta: dict[str, dict] = {}
    for slot, path in action_paths.items():
        normalize_video_for_playback(path)
        actions_meta[slot] = inspect_video(path)
    return idle_meta, actions_meta
