"""文件用途：校验网页生成参数，并为密码保护的设置页面签发短期访问令牌。"""

from __future__ import annotations

import hmac
import os
import secrets
import tempfile
import time
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, StringConstraints

from .config import ProviderMode
from .providers import ALGO_IMAGE_PRESETS, ALGO_VIDEO_PRESETS

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2500)]
# 生图模型要求 32 像素对齐，H.264 成片宽高使用偶数。
ImageDimension = Annotated[int, Field(strict=True, ge=128, le=4096, multiple_of=32)]
VideoDimension = Annotated[int, Field(strict=True, ge=128, le=4096, multiple_of=2)]


class ActionPrompts(BaseModel):
    """一只宠物的待机图、待机视频和左、中、右动作提示词。"""

    image: Prompt
    idle: Prompt
    left: Prompt
    center: Prompt
    right: Prompt


class PetPrompts(BaseModel):
    """分别保存猫咪与狗狗的动作提示词。"""

    cat: ActionPrompts
    dog: ActionPrompts


class GenerationSettings(BaseModel):
    """管理员可编辑的供应商、ComfyUI 输出尺寸及分物种提示词。"""

    provider: ProviderMode
    image_width: ImageDimension = 2560
    image_height: ImageDimension = 1440
    video_width: VideoDimension = 1920
    video_height: VideoDimension = 1080
    prompts: PetPrompts


def default_generation_settings(provider: ProviderMode) -> dict:
    """按启动供应商 provider 生成初始设置，返回可直接写入 SQLite 的字典。"""
    prompts = {}
    for species, pet in (("cat", "猫咪"), ("dog", "狗狗")):
        prompts[species] = {
            "image": ALGO_IMAGE_PRESETS[f"{species}-idle"]["prompt"],
            "idle": (
                f"参考画面中的{pet}保持正面居中趴卧，轻柔呼吸，自然眨眼一次，双前爪留在原位。"
                "保持脸型、毛色花纹、体型、背景和光照一致。固定机位，不伸爪、不探头，"
                "结尾回到开头姿态和视线，自然衔接循环。无切镜、文字和水印。"
            ),
            **{slot: ALGO_VIDEO_PRESETS[f"{species}-{slot}"]["prompt"] for slot in ("left", "center", "right")},
        }
    return GenerationSettings(provider=provider, prompts=prompts).model_dump()


class SettingsLogin(BaseModel):
    """设置页解锁请求，password 为用户在页面输入的密码。"""

    password: SecretStr


class SettingsAccess:
    """用配置密码或本地生成密码认证，令牌仅在本次进程中有效。"""

    def __init__(self, data_dir: Path, password: str):
        self._password = (password or self._load_password(data_dir / "settings-password")).encode()
        self._key = secrets.token_bytes(32)  # 签名密钥仅存在于服务进程内。

    @staticmethod
    def _load_password(path: Path) -> str:
        if not path.exists():
            # 完整写入后再发布，避免并发启动读取到只写了一半的口令。
            with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", encoding="utf-8") as file:
                file.write(secrets.token_urlsafe(18) + "\n")
                file.flush()
                try:
                    os.link(file.name, path)
                except FileExistsError:
                    pass
        return path.read_text(encoding="utf-8").strip()

    def unlock(self, password: str) -> str | None:
        """验证输入的 password，返回 30 分钟有效的令牌，错误时返回 None。"""
        if not self._password or not hmac.compare_digest(password.encode(), self._password):
            return None
        payload = f"{int(time.time()) + 1800}.{secrets.token_hex(16)}"
        signature = hmac.digest(self._key, payload.encode(), "sha256").hex()
        return f"{payload}.{signature}"

    def allows(self, authorization: str) -> bool:
        """验证 Authorization 请求头的签名和有效期，返回是否可访问设置。"""
        prefix, _, token = authorization.partition(" ")
        expires, sep, signed = token.partition(".")
        if prefix != "Bearer" or not sep or len(expires) > 12 or not expires.isascii() or not expires.isdecimal():
            return False
        payload, _, signature = token.rpartition(".")
        if not signed or not signature.isascii():
            return False
        expected = hmac.digest(self._key, payload.encode(), "sha256").hex()
        return int(expires) > time.time() and hmac.compare_digest(signature, expected)
