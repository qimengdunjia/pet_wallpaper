"""文件用途：读取网页 Demo 后端运行参数、数据目录与生成供应商配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
WEB_DEMO_ROOT = BACKEND_ROOT.parent
REPO_ROOT = WEB_DEMO_ROOT.parent

ProviderMode = Literal["mock", "kling"]


def _resolve_path(raw: str | None, default: Path, base: Path) -> Path:
    if not raw:
        return default.resolve()
    candidate = Path(raw)
    return (candidate if candidate.is_absolute() else base / candidate).resolve()


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """封装网页 Demo 后端配置；包含路径、供应商模式和凭据，密钥不出现在日志中。"""

    provider: ProviderMode = "mock"
    data_dir: Path = BACKEND_ROOT / "data"
    assets_dir: Path = WEB_DEMO_ROOT / "assets"
    frontend_dist: Path = WEB_DEMO_ROOT / "frontend" / "dist"
    mock_delay_seconds: float = 2.0
    mock_controls_enabled: bool = True
    kling_api_key: str = field(default="", repr=False)
    kling_base_url: str = "https://api-beijing.klingai.com"
    kling_poll_seconds: float = 15.0
    kling_task_timeout: float = 1800.0
    max_upload_bytes: int = 10 * 1024 * 1024
    disable_worker_lock: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """从 .env 与环境变量加载配置并校验合法性。"""
        load_dotenv(BACKEND_ROOT / ".env", override=False)
        provider_raw = os.getenv("DEMO_PROVIDER", "mock").strip().lower()
        if provider_raw == "comfyui":
            raise ValueError("ComfyUI 工作流请在 algorithm-lab 验证；网页 Demo 支持 DEMO_PROVIDER=mock 或 kling")
        if provider_raw not in {"mock", "kling"}:
            raise ValueError("DEMO_PROVIDER 仅支持 mock 或 kling")
        provider: ProviderMode = provider_raw  # type: ignore[assignment]

        kling_base = os.getenv("KLING_BASE_URL", cls.kling_base_url).strip().rstrip("/")
        parsed_kling = urlparse(kling_base)
        if parsed_kling.scheme != "https" or not parsed_kling.hostname:
            raise ValueError("KLING_BASE_URL 必须是合法的 HTTPS 地址")

        mock_delay = max(0.05, float(os.getenv("DEMO_MOCK_DELAY_SECONDS", str(cls.mock_delay_seconds))))
        mock_controls = _parse_bool(os.getenv("DEMO_MOCK_CONTROLS"), default=(provider == "mock"))

        return cls(
            provider=provider,
            data_dir=_resolve_path(os.getenv("DEMO_DATA_DIR"), BACKEND_ROOT / "data", BACKEND_ROOT),
            assets_dir=_resolve_path(os.getenv("DEMO_ASSETS_DIR"), WEB_DEMO_ROOT / "assets", BACKEND_ROOT),
            frontend_dist=_resolve_path(
                os.getenv("DEMO_FRONTEND_DIST"), WEB_DEMO_ROOT / "frontend" / "dist", BACKEND_ROOT
            ),
            mock_delay_seconds=mock_delay,
            mock_controls_enabled=mock_controls,
            kling_api_key=os.getenv("KLING_API_KEY", "").strip(),
            kling_base_url=kling_base,
            kling_poll_seconds=max(1.0, float(os.getenv("KLING_POLL_SECONDS", str(cls.kling_poll_seconds)))),
            kling_task_timeout=max(30.0, float(os.getenv("KLING_TASK_TIMEOUT_SECONDS", str(cls.kling_task_timeout)))),
            disable_worker_lock=_parse_bool(os.getenv("DEMO_DISABLE_WORKER_LOCK"), default=False),
        )
