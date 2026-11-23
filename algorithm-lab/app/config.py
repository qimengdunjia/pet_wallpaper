"""文件用途：读取仅在后端使用的密钥、区域和本地存储配置。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """封装服务配置；参数为后端配置值，实例供适配层与任务服务读取。"""

    api_key: str = field(default="", repr=False)  # 密钥不进入日志或网页响应。
    base_url: str = "https://api-beijing.klingai.com"  # 默认使用可灵国内节点。
    data_dir: Path = ROOT / "data" / "jobs"  # 每个任务独立保存状态与成品。
    poll_seconds: float = 60
    task_timeout: float = 7200
    max_upload: int = 10 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        """从项目 .env 和进程环境读取配置；无参数，返回校验后的配置。"""
        load_dotenv(ROOT / ".env")
        base = os.getenv("KLING_BASE_URL", cls.base_url).rstrip("/")
        if urlparse(base).scheme != "https" or not urlparse(base).hostname:
            raise ValueError("KLING_BASE_URL 必须是 HTTPS 区域接口地址")
        directory = Path(os.getenv("PET_DATA_DIR", "data/jobs"))
        return cls(
            api_key=os.getenv("KLING_API_KEY", "").strip(), base_url=base,
            data_dir=(ROOT / directory).resolve(),
            poll_seconds=max(1, float(os.getenv("KLING_POLL_SECONDS", "60"))),
            task_timeout=max(60, float(os.getenv("KLING_TASK_TIMEOUT_SECONDS", "7200"))),
        )
