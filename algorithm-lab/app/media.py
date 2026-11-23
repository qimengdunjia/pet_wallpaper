"""文件用途：读取已登记的视频原始规格，供网页验收分辨率、帧率和时长。"""

import json
import subprocess
from fractions import Fraction
from pathlib import Path


class MediaProbeError(Exception):
    """表示本机探测工具或成片元数据不可用。"""


def inspect_video(path: Path) -> dict:
    """探测本地视频。参数 path 为已登记文件，返回像素尺寸、平均帧率和视频时长。"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,avg_frame_rate,duration,sample_aspect_ratio:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, timeout=10)
        data = json.loads(result.stdout)
        video = data["streams"][0]
        width, height = video["width"], video["height"]
        fps = Fraction(video["avg_frame_rate"])
        sar = video.get("sample_aspect_ratio", "N/A")
        pixel_ratio = Fraction(sar.replace(":", "/")) if sar not in {"N/A", "0:1"} else Fraction(1)
        ratio = Fraction(width, height) * pixel_ratio
        duration = video.get("duration", "N/A")
        if duration == "N/A":
            duration = data.get("format", {}).get("duration")
        if fps <= 0 or float(duration) <= 0:
            raise ValueError("无有效帧率或时长")
    except FileNotFoundError as exc:
        raise MediaProbeError("本机未安装 ffprobe。安装 FFmpeg 后可检查实际帧率和文件规格。") from exc
    except (subprocess.SubprocessError, ValueError, ZeroDivisionError, KeyError, IndexError, TypeError) as exc:
        raise MediaProbeError("无法读取该视频的元数据，可尝试下载并在本地播放器检查。") from exc
    return {
        "width": width, "height": height, "fps": float(fps),
        "duration": float(duration), "aspect_ratio": f"{ratio.numerator}:{ratio.denominator}",
    }
