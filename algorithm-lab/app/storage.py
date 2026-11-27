"""文件用途：校验照片，持久化任务版本与素材库，并限制本地文件访问范围。"""

import io
import json
import os
import re
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps, UnidentifiedImageError

from .billing import aggregate_costs
from .image import DEFAULT_IMAGE_OPTIONS

LABELS = {"idle": "待机图", "video": "动作视频"}
JOB_FOLDERS = {"image": "images", "video": "videos"}  # 按测试类型分类存放。
FrameSource = tuple[str, int | None]  # 标识素材来源。上传素材没有任务版本号。
Image.MAX_IMAGE_PIXELS = 40_000_000


def now() -> str:
    """生成 UTC 时间戳；无参数，返回可持久化的 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def normalize_photo(content: bytes) -> bytes:
    """校验并规范化上传照片；参数为文件字节，返回移除元数据的 JPEG 字节。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format not in {"JPEG", "PNG"}:
                    raise ValueError("只支持真实编码为 JPEG 或 PNG 的照片")
                source.load()
                image = ImageOps.exif_transpose(source)
                w, h = image.size
                if min(w, h) < 300 or not 0.4 <= w / h <= 2.5:
                    raise ValueError("照片宽高均需至少 300 像素，宽高比需在 1:2.5～2.5:1 之间")
                image.thumbnail((4096, 4096))
                if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    image = Image.new("RGB", rgba.size, "#eeeeee")
                    image.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    image = image.convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=92)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("无法读取照片，文件可能损坏或像素过大") from exc


class JobStore:
    """管理本地任务、素材库和提示词预设；参数 root 为本机数据根目录。"""

    def __init__(self, root: Path):
        self.root = root
        self.uploads = root / "idle-image-uploads"  # 单独保存用户上传的素材图片及原始文件名。
        self.removed_images = root / "removed-idle-images.json"  # 按任务 ID 记录已移出的版本号。
        root.mkdir(parents=True, exist_ok=True)

    def directory(self, job_id: str, kind: str | None = None) -> Path:
        """定位任务目录；参数为任务 ID 和可选类型，返回对应分类目录。"""
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise FileNotFoundError("任务不存在")
        if kind is not None:
            return self.root / JOB_FOLDERS[kind] / job_id
        for folder in JOB_FOLDERS.values():
            candidate = self.root / folder / job_id
            if candidate.is_dir():
                return candidate
        raise FileNotFoundError("任务不存在")

    def load(self, job_id: str) -> dict:
        """读取一个任务；参数为任务 ID，返回完整内部状态。"""
        job = json.loads((self.directory(job_id) / "job.json").read_text())
        if job["kind"] == "image":
            job.setdefault("image_options", DEFAULT_IMAGE_OPTIONS.model_dump())
        return job

    def save(self, job: dict) -> None:
        """原子保存任务；参数为完整状态，返回空，替换前同步临时文件。"""
        directory = self.directory(job["id"], job["kind"])
        directory.mkdir(exist_ok=True)
        job["updated_at"] = now()
        _write_json(directory / "job.json", job)

    def prompt_presets(self, kind: str) -> dict:
        """读取提示词预设。参数 kind 为测试类型，返回按预设 ID 索引的本机记录。"""
        try:
            return json.loads(self._prompt_path(kind).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def save_prompt_presets(self, kind: str, presets: dict) -> None:
        """原子保存提示词预设。参数为测试类型和完整预设字典，无返回值。"""
        _write_json(self._prompt_path(kind), presets)

    def _prompt_path(self, kind: str) -> Path:
        return self.root / f"prompt-presets-{JOB_FOLDERS[kind]}.json"

    def all(self) -> list[dict]:
        """读取全部可用任务；无参数，返回按创建时间倒序排列的任务列表。"""
        jobs = []
        for folder in JOB_FOLDERS.values():
            directory = self.root / folder
            for path in directory.glob("*/job.json"):
                try:
                    jobs.append(self.load(path.parent.name))
                except (OSError, ValueError, KeyError):
                    continue
        return sorted(jobs, key=lambda job: job["created_at"], reverse=True)

    def file(self, job: dict, name: str) -> Path:
        """取得登记的成品；参数为任务与文件名，返回安全路径，未登记则抛出异常。"""
        allowed = set(self.reference_names(job))
        if tail := job["input"].get("tail_file"):
            allowed.add(tail)
        allowed.update(job["input"].get("video_reference_files", []))
        for stage in job["stages"].values():
            allowed.update(a["output"]["file"] for a in stage["attempts"] if a.get("output"))
        path = self.directory(job["id"], job["kind"]) / name
        if name not in allowed or path.name != name or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("文件不存在")
        return path

    def reference_names(self, job: dict) -> list[str]:
        """按发送顺序返回已登记的输入文件名；换猫任务将底图放在首位。"""
        source = job["input"]
        if base := source.get("style_file"):
            return [base, source["file"]]
        return [source["file"], *source.get("reference_files", [])]

    def public(self, job: dict) -> dict:
        """导出浏览器状态；参数为内部任务，返回不含密钥、远端签名链接的摘要。"""
        def local_url(name):
            return f"/api/jobs/{job['id']}/files/{name}"

        stages = {}
        for key, stage in job["stages"].items():
            current = next((a for a in stage["attempts"] if a["number"] == stage["current"]), None)
            output = current.get("output") if current else None
            attempt_costs = [a.get("cost") for a in stage["attempts"] if a.get("cost")]
            stages[key] = {
                "label": LABELS[key], "state": stage["state"], "stale": stage["stale"],
                "version": stage["current"], "url": local_url(output["file"]) if output else None,
                "attempt_count": len(stage["attempts"]),
                "current_cost": current.get("cost") if current else None,
                "total_cost": aggregate_costs(attempt_costs),
                "attempt": {k: stage["attempts"][-1].get(k) for k in
                            ("number", "state", "provider_id", "inputs", "error", "resumable", "cost")}
                if stage["attempts"] else None,
            }
        return {
            "id": job["id"], "status": job["status"], "active_stage": job.get("active_stage"),
            "kind": job["kind"],
            "preset": job.get("preset"),
            "batch_id": job.get("batch_id"),
            "batch_index": job.get("batch_index"),
            "created_at": job["created_at"], "updated_at": job["updated_at"],
            "input_url": local_url(job["input"]["file"]), "stages": stages,
            "reference_urls": [local_url(name) for name in self.reference_names(job)]
            if job["kind"] == "image" else [],
            "style_url": local_url(job["input"]["style_file"]) if job["input"].get("style_file") else None,
            "tail_url": local_url(job["input"]["tail_file"]) if job["input"].get("tail_file") else None,
            "video_reference_urls": [local_url(name) for name in job["input"].get("video_reference_files", [])],
            "image_prompt": job.get("image_prompt"),
            "image_options": job.get("image_options"),
            "idle_source": job["input"].get("idle_source"),
            "tail_source": job["input"].get("tail_source"),
            "video_prompt": job.get("video_prompt"),
            "video_options": job["video_options"],
            "error": job.get("error"),
        }

    def idle_image(self, job: dict, version: int) -> Path:
        """取得已生成的待机图；参数为来源任务和版本，返回登记过的本地图片路径。"""
        for attempt in job["stages"].get("idle", {}).get("attempts", []):
            if attempt["number"] == version and attempt["state"] == "complete" and attempt.get("output"):
                return self.file(job, attempt["output"]["file"])
        raise FileNotFoundError("待机图版本不存在")

    def _removed_versions(self) -> dict[str, list[int]]:
        try:
            return json.loads(self.removed_images.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}

    def uploaded_image(self, asset_id: str) -> Path:
        """定位上传素材；参数为素材 ID，返回登记的 JPEG 路径。"""
        if not re.fullmatch(r"[a-f0-9]{32}", asset_id):
            raise FileNotFoundError("上传素材不存在")
        path = self.uploads / asset_id / "image.jpg"
        if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
            raise FileNotFoundError("上传素材不存在")
        return path

    def add_idle_image(self, content: bytes, filename: str) -> dict:
        """保存用户上传的素材；参数为已校验的 JPEG 和原文件名，返回素材记录。"""
        asset_id = uuid.uuid4().hex
        name = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()[:120] or "上传图片"
        image = {
            "asset_id": asset_id, "name": name, "created_at": now(),
            "url": f"/api/idle-images/uploads/{asset_id}",
        }
        self.uploads.mkdir(exist_ok=True)
        # 完成图片和元数据写入后一次性发布，避免列出半成品。
        with TemporaryDirectory(dir=self.uploads, prefix=".adding-") as temporary:
            pending = Path(temporary) / asset_id
            pending.mkdir()
            (pending / "image.jpg").write_bytes(content)
            _write_json(pending / "image.json", image)
            pending.rename(self.uploads / asset_id)
        return image

    def remove_idle_image(self, source: FrameSource) -> None:
        """移除素材；参数为素材来源，上传素材删除副本，生成图仅移出素材库。"""
        identifier, version = source
        if version is None:
            directory = self.uploaded_image(identifier).parent
            with TemporaryDirectory(dir=self.uploads, prefix=".removing-") as temporary:
                directory.rename(Path(temporary) / identifier)
            return
        self.idle_image(self.load(identifier), version)
        removed = self._removed_versions()
        versions = removed.setdefault(identifier, [])
        if version not in versions:
            versions.append(version)
            _write_json(self.removed_images, removed)

    def frame_source(self, source: FrameSource) -> tuple[Path, dict]:
        """解析首尾帧素材；参数为素材来源，返回当前可用的图片路径和任务溯源字段。"""
        identifier, version = source
        if version is None:
            return self.uploaded_image(identifier), {"asset_id": identifier}
        if version in self._removed_versions().get(identifier, []):
            raise FileNotFoundError("待机图已移出素材库")
        return self.idle_image(self.load(identifier), version), {"job_id": identifier, "version": version}

    def idle_images(self) -> list[dict]:
        """列出可选的上传图片和生成图版本；无参数，返回按添加或出图时间倒序排列的素材。"""
        images = []
        for metadata in self.uploads.glob("*/image.json"):
            try:
                self.uploaded_image(metadata.parent.name)
                images.append(json.loads(metadata.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        removed = self._removed_versions()
        for job in self.all():
            versions = removed.get(job["id"], [])
            for attempt in job["stages"].get("idle", {}).get("attempts", []):
                if attempt["state"] != "complete" or not attempt.get("output") or attempt["number"] in versions:
                    continue
                try:
                    path = self.file(job, attempt["output"]["file"])
                except FileNotFoundError:
                    continue
                images.append({
                    "job_id": job["id"], "version": attempt["number"], "preset": job.get("preset"),
                    "created_at": attempt.get("finished_at") or attempt["created_at"],
                    "url": f"/api/jobs/{job['id']}/files/{path.name}",
                })
        return sorted(images, key=lambda image: image["created_at"], reverse=True)
