"""文件用途：使用 SQLite 持久化宠物档案、异步生成任务、素材版本与上次成功壁纸记录。"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """生成带 UTC 时区的 ISO 8601 时间戳。"""
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS pets (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    species TEXT NOT NULL CHECK (species IN ('cat', 'dog')),
    name TEXT NOT NULL,
    gender TEXT NOT NULL DEFAULT '未设置',
    breed TEXT NOT NULL DEFAULT '',
    original_photo_path TEXT,
    active_version_id TEXT,
    latest_job_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pets_session ON pets(session_id, created_at);

CREATE TABLE IF NOT EXISTS generation_jobs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    pet_id TEXT NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued', 'generating', 'ready', 'failed')),
    stage TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0,
    photo_path TEXT NOT NULL,
    remote_tasks_json TEXT NOT NULL DEFAULT '{}',
    mock_options_json TEXT NOT NULL DEFAULT '{}',
    generation_config_json TEXT NOT NULL DEFAULT '{}',
    version_id TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_jobs_session ON generation_jobs(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON generation_jobs(status);

CREATE TABLE IF NOT EXISTS asset_versions (
    id TEXT PRIMARY KEY,
    pet_id TEXT NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    idle_image_path TEXT NOT NULL,
    idle_meta_json TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    validated INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_versions_pet ON asset_versions(pet_id, version_number DESC);

CREATE TABLE IF NOT EXISTS current_wallpapers (
    session_id TEXT PRIMARY KEY,
    pet_id TEXT NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
    version_id TEXT NOT NULL REFERENCES asset_versions(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    settings_json TEXT NOT NULL
);
"""


def _row_to_pet(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "species": row["species"],
        "name": row["name"],
        "gender": row["gender"],
        "breed": row["breed"],
        "original_photo_path": row["original_photo_path"],
        "active_version_id": row["active_version_id"],
        "latest_job_id": row["latest_job_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_job(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "pet_id": row["pet_id"],
        "idempotency_key": row["idempotency_key"],
        "provider": row["provider"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "photo_path": row["photo_path"],
        "remote_tasks": json.loads(row["remote_tasks_json"]),
        "mock_options": json.loads(row["mock_options_json"]),
        "generation_config": json.loads(row["generation_config_json"]),  # 提交时冻结的生成参数。
        "version_id": row["version_id"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_to_version(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "pet_id": row["pet_id"],
        "job_id": row["job_id"],
        "version_number": row["version_number"],
        "idle_image_path": row["idle_image_path"],
        "idle_meta": json.loads(row["idle_meta_json"]),
        "actions": json.loads(row["actions_json"]),
        "validated": bool(row["validated"]),
        "created_at": row["created_at"],
    }


class GenerationKeyConflict(Exception):
    """表示幂等键已存在，job 保存当前会话中占用该键的任务。"""

    def __init__(self, job: dict):
        super().__init__("生成任务幂等键已存在")
        self.job = job


class DemoDatabase:
    """线程安全的 SQLite 状态仓库。"""

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA_SQL)
            job_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(generation_jobs)")}
            if "generation_config_json" not in job_columns:
                self._conn.execute("ALTER TABLE generation_jobs ADD COLUMN generation_config_json TEXT NOT NULL DEFAULT '{}'")

    def get_generation_settings(self) -> dict | None:
        """读取管理员保存的生成设置；尚未保存时返回 None。"""
        with self._lock:
            row = self._conn.execute("SELECT settings_json FROM generation_settings WHERE id = 1").fetchone()
        return json.loads(row["settings_json"]) if row else None

    def save_generation_settings(self, settings: dict) -> None:
        """将已校验的生成设置整体写入 SQLite，无返回值。"""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO generation_settings (id, settings_json) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET settings_json = excluded.settings_json",
                (json.dumps(settings, ensure_ascii=False),),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create_pet(
        self,
        session_id: str,
        species: str,
        name: str,
        gender: str = "未设置",
        breed: str = "",
    ) -> dict:
        pet_id = uuid.uuid4().hex
        ts = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO pets (id, session_id, species, name, gender, breed, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (pet_id, session_id, species, name, gender, breed, ts, ts),
            )
            row = self._conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
        assert row is not None
        return _row_to_pet(row)

    def get_pet(self, session_id: str, pet_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM pets WHERE id = ? AND session_id = ?", (pet_id, session_id)
            ).fetchone()
        return _row_to_pet(row) if row else None

    def get_pet_any(self, pet_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
        return _row_to_pet(row) if row else None

    def list_pets(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pets WHERE session_id = ? ORDER BY created_at ASC", (session_id,)
            ).fetchall()
        return [_row_to_pet(r) for r in rows]

    def update_pet(
        self,
        session_id: str,
        pet_id: str,
        *,
        name: str | None = None,
        gender: str | None = None,
        breed: str | None = None,
    ) -> dict | None:
        with self._lock, self._conn:
            current = self._conn.execute(
                "SELECT * FROM pets WHERE id = ? AND session_id = ?", (pet_id, session_id)
            ).fetchone()
            if not current:
                return None
            new_name = name if name is not None else current["name"]
            new_gender = gender if gender is not None else current["gender"]
            new_breed = breed if breed is not None else current["breed"]
            ts = now_iso()
            self._conn.execute(
                "UPDATE pets SET name = ?, gender = ?, breed = ?, updated_at = ? WHERE id = ?",
                (new_name, new_gender, new_breed, ts, pet_id),
            )
            row = self._conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
        return _row_to_pet(row) if row else None

    def set_pet_original_photo(self, pet_id: str, photo_path: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE pets SET original_photo_path = ?, updated_at = ? WHERE id = ?",
                (photo_path, now_iso(), pet_id),
            )

    def get_job_by_idempotency(self, session_id: str, idempotency_key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM generation_jobs WHERE session_id = ? AND idempotency_key = ?",
                (session_id, idempotency_key),
            ).fetchone()
        return _row_to_job(row) if row else None

    def create_generation_job(
        self,
        session_id: str,
        pet_id: str,
        idempotency_key: str,
        provider: str,
        photo_path: str,
        mock_options: dict | None = None,
        generation_config: dict | None = None,
    ) -> dict:
        """为指定会话和宠物保存照片引用、供应商、模拟选项及生成参数快照，返回排队任务。

        幂等键已存在时抛出 GenerationKeyConflict，保留原任务及宠物档案。
        """
        job_id = uuid.uuid4().hex
        ts = now_iso()
        with self._lock, self._conn:
            inserted = self._conn.execute(
                """
                INSERT INTO generation_jobs (
                    id, session_id, pet_id, idempotency_key, provider, status, stage, progress,
                    photo_path, remote_tasks_json, mock_options_json, generation_config_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, 'queued', 'queued', 0, ?, '{}', ?, ?, ?, ?)
                ON CONFLICT(session_id, idempotency_key) DO NOTHING
                """,
                (
                    job_id,
                    session_id,
                    pet_id,
                    idempotency_key,
                    provider,
                    photo_path,
                    json.dumps(mock_options or {}, ensure_ascii=False),
                    json.dumps(generation_config or {}, ensure_ascii=False),
                    ts,
                    ts,
                ),
            )
            if inserted.rowcount == 0:
                existing = self.get_job_by_idempotency(session_id, idempotency_key)
                assert existing is not None
                raise GenerationKeyConflict(existing)
            self._conn.execute(
                "UPDATE pets SET latest_job_id = ?, original_photo_path = ?, updated_at = ? WHERE id = ?",
                (job_id, photo_path, ts, pet_id),
            )
            row = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        assert row is not None
        return _row_to_job(row)

    def get_job(self, session_id: str, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM generation_jobs WHERE id = ? AND session_id = ?", (job_id, session_id)
            ).fetchone()
        return _row_to_job(row) if row else None

    def get_job_any(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM generation_jobs WHERE session_id = ? ORDER BY created_at DESC LIMIT 50",
                (session_id,),
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def list_incomplete_jobs(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM generation_jobs WHERE status IN ('queued', 'generating') ORDER BY created_at ASC"
            ).fetchall()
        return [_row_to_job(r) for r in rows]

    def update_job_progress(
        self,
        job_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        progress: int | None = None,
        remote_tasks: dict | None = None,
    ) -> dict | None:
        with self._lock, self._conn:
            current = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
            if not current:
                return None
            new_status = status if status is not None else current["status"]
            new_stage = stage if stage is not None else current["stage"]
            new_progress = progress if progress is not None else current["progress"]
            new_remote = (
                json.dumps(remote_tasks, ensure_ascii=False)
                if remote_tasks is not None
                else current["remote_tasks_json"]
            )
            self._conn.execute(
                """
                UPDATE generation_jobs
                SET status = ?, stage = ?, progress = ?, remote_tasks_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_status, new_stage, new_progress, new_remote, now_iso(), job_id),
            )
            row = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def fail_job(
        self,
        job_id: str,
        *,
        stage: str | None = None,
        error_message: str,
        remote_tasks: dict | None = None,
    ) -> dict | None:
        with self._lock, self._conn:
            current = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
            if not current:
                return None
            new_stage = stage if stage is not None else current["stage"]
            new_remote = (
                json.dumps(remote_tasks, ensure_ascii=False)
                if remote_tasks is not None
                else current["remote_tasks_json"]
            )
            self._conn.execute(
                """
                UPDATE generation_jobs
                SET status = 'failed', stage = ?, error_message = ?, remote_tasks_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_stage, error_message, new_remote, now_iso(), job_id),
            )
            row = self._conn.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def publish_version(
        self,
        job_id: str,
        pet_id: str,
        idle_image_path: str,
        idle_meta: dict,
        actions_meta: dict[str, dict],
        remote_tasks: dict | None = None,
    ) -> dict:
        version_id = uuid.uuid4().hex
        ts = now_iso()
        with self._lock, self._conn:
            max_row = self._conn.execute(
                "SELECT COALESCE(MAX(version_number), 0) AS max_ver FROM asset_versions WHERE pet_id = ?",
                (pet_id,),
            ).fetchone()
            version_number = int(max_row["max_ver"]) + 1
            self._conn.execute(
                """
                INSERT INTO asset_versions (
                    id, pet_id, job_id, version_number, idle_image_path, idle_meta_json, actions_json, validated, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    version_id,
                    pet_id,
                    job_id,
                    version_number,
                    idle_image_path,
                    json.dumps(idle_meta, ensure_ascii=False),
                    json.dumps(actions_meta, ensure_ascii=False),
                    ts,
                ),
            )
            self._conn.execute(
                "UPDATE pets SET active_version_id = ?, updated_at = ? WHERE id = ?",
                (version_id, ts, pet_id),
            )
            remote_sql = (
                ", remote_tasks_json = ?" if remote_tasks is not None else ""
            )
            params: list = ["ready", "ready", 100, version_id, None, ts]
            if remote_tasks is not None:
                params.append(json.dumps(remote_tasks, ensure_ascii=False))
            params.append(job_id)
            self._conn.execute(
                f"""
                UPDATE generation_jobs
                SET status = ?, stage = ?, progress = ?, version_id = ?, error_message = ?, updated_at = ?
                {remote_sql}
                WHERE id = ?
                """,
                params,
            )
            row = self._conn.execute("SELECT * FROM asset_versions WHERE id = ?", (version_id,)).fetchone()
        assert row is not None
        return _row_to_version(row)

    def get_version(self, version_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM asset_versions WHERE id = ?", (version_id,)).fetchone()
        return _row_to_version(row) if row else None

    def get_version_for_session(self, session_id: str, version_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT v.*
                FROM asset_versions v
                JOIN pets p ON p.id = v.pet_id
                WHERE v.id = ? AND p.session_id = ?
                """,
                (version_id, session_id),
            ).fetchone()
        return _row_to_version(row) if row else None

    def get_current_wallpaper(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM current_wallpapers WHERE session_id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "session_id": row["session_id"],
            "pet_id": row["pet_id"],
            "version_id": row["version_id"],
            "updated_at": row["updated_at"],
        }

    def set_current_wallpaper(self, session_id: str, pet_id: str, version_id: str) -> dict:
        ts = now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO current_wallpapers (session_id, pet_id, version_id, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    pet_id = excluded.pet_id,
                    version_id = excluded.version_id,
                    updated_at = excluded.updated_at
                """,
                (session_id, pet_id, version_id, ts),
            )
        return {
            "session_id": session_id,
            "pet_id": pet_id,
            "version_id": version_id,
            "updated_at": ts,
        }

    def clear_current_wallpaper(self, session_id: str) -> None:
        """清除当前会话保存的自定义壁纸记录，恢复回默认壁纸状态。"""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM current_wallpapers WHERE session_id = ?", (session_id,))
