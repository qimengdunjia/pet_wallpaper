"""文件用途：下载并校验服务器 ComfyUI 所需的 MiniMax H3 Image 权重。"""

import argparse
import hashlib
from pathlib import Path

from huggingface_hub import hf_hub_download


# 固定官方仓库版本、文件大小与摘要，避免下载中途版本变化。
REPOSITORY = "Comfy-Org/MiniMax-H3-Image"
REVISION = "0bb149f51e3156ed4b90dd45d5620346bfe1df8f"
FILES = {
    "diffusion_models/minimax_h3_image_pruned_int8_convrot.safetensors": (
        20979314802,
        "83eb140f1ff95c068f8a6886e6d3f3d0d4ab2e07bb2fe6d2ef992a51146ee622",
    ),
    "vae/minimax_h3_image_vae_fp16.safetensors": (
        1168505312,
        "d80e9c2e5cfc9844869961ff5a58c9a9e52182df6bfb30b26018dd7f348721af",
    ),
}


def verify(path, expected_size, expected_sha256):
    """校验文件完整性；参数为路径、字节数、SHA-256，无返回值，失败抛异常。"""
    if path.stat().st_size != expected_size:
        raise RuntimeError(f"文件大小不匹配：{path}")
    with path.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(f"SHA-256 不匹配：{path}")


def main():
    """按命令行指定的 ComfyUI 目录部署两份权重，复用已通过校验的文件。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comfy_root", type=Path)
    args = parser.parse_args()
    model_root = args.comfy_root.resolve() / "models"
    staging = args.comfy_root.resolve().parent / "minimax-image-download"
    for name, (size, digest) in FILES.items():
        target = model_root / name
        if not target.is_file():
            print(f"下载：{name}", flush=True)
            downloaded = Path(hf_hub_download(
                REPOSITORY, name, revision=REVISION, local_dir=staging, token=False,
            ))
            verify(downloaded, size, digest)
            target.parent.mkdir(parents=True, exist_ok=True)
            downloaded.replace(target)
        else:
            verify(target, size, digest)
        print(f"校验完成：{target}", flush=True)


if __name__ == "__main__":
    main()
