"""Hub 停机后的清理核查；共享申请凭据没有此维护能力。"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, Field

from runbridge_hub.protocol import Identifier, Model
from runbridge_hub.store import Store


class CleanupEvidence(Model):
    """由设备维护者核查原范围后提供的记录，不冒充 Node 确认。"""

    node_id: Identifier
    grant_id: Identifier
    checked_at: AwareDatetime
    details: str = Field(min_length=1, max_length=16000)


def confirm_cleanup(*, database_path: Path, grant_id: str, evidence_file: Path) -> None:
    """只处理精确租约；设备停止由操作者核查，运行中的 Hub 由锁拒绝。"""
    if not database_path.is_file():
        raise ValueError("数据库不存在，不能创建空库作为核查结果")
    evidence = CleanupEvidence.model_validate_json(evidence_file.read_text(encoding="utf-8"))
    if evidence.grant_id != grant_id:
        raise ValueError("证据中的 grant_id 与目标不符")
    store = Store(path=database_path)
    store.acquire_process_lock()
    try:
        with sqlite3.connect(store.path) as db:
            db.row_factory = sqlite3.Row
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in {1, 2, 3, 4, 5}:
                raise ValueError("数据库版本不支持离线核查")
            record = db.execute("SELECT * FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
            if record is None or record["node_id"] != evidence.node_id:
                raise ValueError("证据不属于该 Node 的原租约")
            if evidence.checked_at < datetime.fromisoformat(record["created_at"]) or evidence.checked_at > datetime.now(UTC):
                raise ValueError("核查时间必须位于原租约创建和当前时间之间")
            has_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='grant_resolutions'").fetchone()
            old = db.execute("SELECT evidence FROM grant_resolutions WHERE grant_id=?", (grant_id,)).fetchone() if has_table else None
            if old:
                if CleanupEvidence.model_validate_json(old[0]) == evidence:
                    return
                raise ValueError("原租约已有核查证据，不能覆盖")
            if version == 5 and record["state"] != "QUARANTINED":
                raise ValueError("当前只允许核查 QUARANTINED 租约")
            backup_path = store.path.with_name(f"{store.path.name}.pre-cleanup-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f')}.bak")
            with sqlite3.connect(backup_path) as backup:
                db.backup(backup)
            db.execute("CREATE TABLE IF NOT EXISTS grant_resolutions (grant_id TEXT PRIMARY KEY REFERENCES grants(grant_id),recorded_at TEXT NOT NULL,evidence TEXT NOT NULL)")
            db.execute("INSERT INTO grant_resolutions VALUES (?,?,?)", (grant_id, datetime.now(UTC).isoformat(), evidence.model_dump_json()))
            if version == 5:
                db.execute("UPDATE grants SET state='RELEASED',released_at=? WHERE grant_id=?", (datetime.now(UTC).isoformat(), grant_id))
    finally:
        store.process_lock.close()
