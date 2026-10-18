"""SQLite 中保存登记、许可与能力快照，不保存活连接。"""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


MCP_REQUEST_LIMIT = 1024


class Store:
    """使用单连接线程与短事务串行维护元数据。"""

    def __init__(self, *, path: Path):
        self.path = path
        self.connection = None
        self.lock = asyncio.Lock()

    async def open(self) -> None:
        """迁移至版本 4，保留旧会话并增加无载荷的指令记录。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(database=str(self.path))
        self.connection.row_factory = aiosqlite.Row
        async with self.connection.execute("PRAGMA user_version") as cursor:
            version = (await cursor.fetchone())[0]
        if version not in {0, 1, 2, 3, 4}:
            await self.connection.close()
            raise RuntimeError("数据库版本不受支持")
        await self.connection.executescript("""
            PRAGMA foreign_keys = ON;
            PRAGMA journal_mode = WAL;
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                token_hash TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
                capabilities TEXT, capabilities_observed_at TEXT, last_seen_at TEXT
            );
            CREATE TABLE IF NOT EXISTS grants (
                grant_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(node_id),
                token_hash TEXT NOT NULL UNIQUE, resource_ids TEXT,
                created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(node_id),
                grant_id TEXT NOT NULL REFERENCES grants(grant_id), record TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS mcp_requests (
                grant_id TEXT NOT NULL REFERENCES grants(grant_id),
                node_id TEXT NOT NULL REFERENCES nodes(node_id), request_id TEXT NOT NULL,
                arguments TEXT NOT NULL, state TEXT NOT NULL,
                session_id TEXT REFERENCES sessions(session_id), page_id TEXT,
                error_code TEXT, execution_outcome TEXT,
                PRIMARY KEY (grant_id, node_id, request_id)
            );
            CREATE TABLE IF NOT EXISTS commands (
                grant_id TEXT NOT NULL REFERENCES grants(grant_id),
                session_id TEXT NOT NULL REFERENCES sessions(session_id), request_id TEXT NOT NULL,
                digest TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL,
                execution_outcome TEXT NOT NULL, error_code TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (grant_id, session_id, request_id)
            );
            PRAGMA user_version = 4;
        """)
        await self.connection.commit()

    async def close(self) -> None:
        """关闭元数据连接。"""
        if self.connection is not None:
            await self.connection.close()

    async def node(self, *, node_id: str) -> dict | None:
        """查询一个登记记录。

        :param node_id: 节点 ID。
        :returns: 记录或空值。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row is not None else None

    async def register(self, *, node_id: str, name: str, token_digest: str) -> tuple[dict, bool]:
        """登记新身份或返回已有身份，已有凭据不能被覆盖。

        :param node_id: 节点 ID。
        :param name: 显示名称。
        :param token_digest: 节点凭据摘要。
        :returns: 登记记录与是否新建。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)) as cursor:
                existing = await cursor.fetchone()
            if existing is not None:
                return dict(existing), False
            await self.connection.execute("INSERT INTO nodes (node_id, name, token_hash) VALUES (?, ?, ?)", (node_id, name, token_digest))
            await self.connection.commit()
            return {"node_id": node_id, "name": name, "token_hash": token_digest}, True

    async def next_generation(self, *, node_id: str, observed_at: str) -> int:
        """为认证后的连接分配持久递增代次。

        :param node_id: 节点 ID。
        :param observed_at: 服务器观察时间。
        :returns: 新连接代次。
        """
        async with self.lock:
            await self.connection.execute("UPDATE nodes SET generation = generation + 1, last_seen_at = ? WHERE node_id = ?", (observed_at, node_id))
            async with self.connection.execute("SELECT generation FROM nodes WHERE node_id = ?", (node_id,)) as cursor:
                generation = (await cursor.fetchone())[0]
            await self.connection.commit()
            return generation

    async def snapshot(self, *, node_id: str, generation: int, capabilities: str, observed_at: str) -> None:
        """只允许当前连接代次保存能力快照。

        :param node_id: 节点 ID。
        :param generation: 当前连接代次。
        :param capabilities: JSON 快照。
        :param observed_at: 服务器观察时间。
        """
        async with self.lock:
            await self.connection.execute("UPDATE nodes SET capabilities = ?, capabilities_observed_at = ?, last_seen_at = ? WHERE node_id = ? AND generation = ?", (capabilities, observed_at, observed_at, node_id, generation))
            await self.connection.commit()

    async def disconnected(self, *, node_id: str, generation: int, last_seen_at: str) -> None:
        """断开时保存最后观察时间，心跳不逐条落库。

        :param node_id: 节点 ID。
        :param generation: 断开的连接代次。
        :param last_seen_at: 最后观察时间。
        """
        async with self.lock:
            await self.connection.execute("UPDATE nodes SET last_seen_at = ? WHERE node_id = ? AND generation = ?", (last_seen_at, node_id, generation))
            await self.connection.commit()

    async def create_grant(self, *, values: dict) -> None:
        """保存一个访问许可及其摘要。

        :param values: 不含凭据原值的许可记录。
        """
        async with self.lock:
            await self.connection.execute("INSERT INTO grants (grant_id, node_id, token_hash, resource_ids, created_at, expires_at) VALUES (:grant_id, :node_id, :token_hash, :resource_ids, :created_at, :expires_at)", values)
            await self.connection.commit()

    async def grant_by_token(self, *, token_digest: str) -> dict | None:
        """通过摘要查找许可。

        :param token_digest: 对接凭据摘要。
        :returns: 许可或空值。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM grants WHERE token_hash = ?", (token_digest,)) as cursor:
                row = await cursor.fetchone()
                return self._grant(row=row) if row is not None else None

    async def grants(self, *, node_id: str) -> list[dict]:
        """列出节点许可，不含凭据原值。

        :param node_id: 节点 ID。
        :returns: 许可记录。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM grants WHERE node_id = ? ORDER BY created_at", (node_id,)) as cursor:
                return [self._grant(row=row) for row in await cursor.fetchall()]

    async def revoke(self, *, node_id: str, grant_id: str, revoked_at: str) -> bool:
        """撤销指定节点的许可。

        :param node_id: 节点 ID。
        :param grant_id: 许可 ID。
        :param revoked_at: 撤销时间。
        :returns: 许可是否存在。
        """
        async with self.lock:
            cursor = await self.connection.execute("UPDATE grants SET revoked_at = COALESCE(revoked_at, ?) WHERE node_id = ? AND grant_id = ?", (revoked_at, node_id, grant_id))
            await self.connection.commit()
            return cursor.rowcount > 0

    async def save_session(self, *, session_id: str, node_id: str, grant_id: str, record: str, mcp_request_id: str | None = None) -> None:
        """保存会话生命周期元数据，协议帧不落库。

        :param session_id: 会话 ID。
        :param node_id: 节点 ID。
        :param grant_id: 许可 ID。
        :param record: 不含秘密的会话 JSON。
        :param mcp_request_id: 首次分配时原子关联的 MCP 请求标识。
        """
        async with self.lock:
            try:
                await self.connection.execute("INSERT INTO sessions (session_id, node_id, grant_id, record) VALUES (?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET record = excluded.record", (session_id, node_id, grant_id, record))
                if mcp_request_id is not None:
                    cursor = await self.connection.execute("UPDATE mcp_requests SET session_id = ? WHERE grant_id = ? AND node_id = ? AND request_id = ? AND state = 'PENDING' AND session_id IS NULL", (session_id, grant_id, node_id, mcp_request_id))
                    if cursor.rowcount != 1:
                        raise ValueError("MCP 请求不能重复分配会话")
                await self.connection.commit()
            except BaseException:
                await self.connection.rollback()
                raise

    async def mcp_request(self, *, key: tuple[str, str, str]) -> dict | None:
        """查询精确许可、节点和请求的无凭据记录。

        :returns: 请求记录或空值。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM mcp_requests WHERE grant_id = ? AND node_id = ? AND request_id = ?", key) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row is not None else None

    async def begin_mcp_request(self, *, key: tuple[str, str, str], arguments: dict) -> tuple[dict | None, bool]:
        """保留同键记录；只回收已失效许可，达到容量时不分配资源。

        :returns: 记录与是否首次受理；记录为空表示容量已满。
        """
        async with self.lock:
            async with self.connection.execute("SELECT * FROM mcp_requests WHERE grant_id = ? AND node_id = ? AND request_id = ?", key) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                return dict(row), False
            await self.connection.execute("DELETE FROM mcp_requests WHERE grant_id IN (SELECT grant_id FROM grants WHERE revoked_at IS NOT NULL OR (expires_at IS NOT NULL AND julianday(expires_at) <= julianday(?)))", (datetime.now(UTC).isoformat(),))
            async with self.connection.execute("SELECT COUNT(*) FROM mcp_requests WHERE grant_id = ?", (key[0],)) as cursor:
                count = (await cursor.fetchone())[0]
            if count >= MCP_REQUEST_LIMIT:
                await self.connection.commit()
                return None, False
            serialized = json.dumps(arguments, sort_keys=True)
            await self.connection.execute("INSERT INTO mcp_requests (grant_id, node_id, request_id, arguments, state) VALUES (?, ?, ?, ?, 'PENDING')", (*key, serialized))
            await self.connection.commit()
            return {"grant_id": key[0], "node_id": key[1], "request_id": key[2], "arguments": serialized, "state": "PENDING", "session_id": None, "page_id": None, "error_code": None, "execution_outcome": None}, True

    async def finish_mcp_request(self, *, key: tuple[str, str, str], state: str, page_id: str | None = None, error_code: str | None = None) -> None:
        """仅保存终态必要字段，不保存 Task、异常或访问凭据。"""
        async with self.lock:
            await self.connection.execute("UPDATE mcp_requests SET state = ?, page_id = ?, error_code = ?, execution_outcome = CASE WHEN ? = 'SUCCEEDED' THEN NULL WHEN ? = 'FAILED' AND session_id IS NULL THEN 'NOT_STARTED' ELSE 'OUTCOME_UNKNOWN' END WHERE grant_id = ? AND node_id = ? AND request_id = ?", (state, page_id, error_code, state, state, *key))
            await self.connection.commit()

    async def interrupt_mcp_requests(self) -> None:
        """重启不重放上次未完成请求，保留已分配的会话关联。"""
        async with self.lock:
            await self.connection.execute("UPDATE mcp_requests SET state = 'UNKNOWN', error_code = 'REQUEST_OUTCOME_UNKNOWN', execution_outcome = 'OUTCOME_UNKNOWN' WHERE state = 'PENDING'")
            await self.connection.commit()

    async def session(self, *, session_id: str) -> dict | None:
        """查询持久会话元数据。

        :returns: JSON 对象或空值。
        """
        async with self.lock:
            async with self.connection.execute("SELECT record FROM sessions WHERE session_id = ?", (session_id,)) as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if row is not None else None

    async def unfinished_sessions(self) -> list[dict]:
        """读取启动时需要标为中断的会话。

        :returns: 未结束的元数据。
        """
        async with self.lock:
            async with self.connection.execute("SELECT record FROM sessions WHERE json_extract(record, '$.state') IN ('PREPARING', 'READY', 'ACTIVE', 'CLOSING')") as cursor:
                return [json.loads(row[0]) for row in await cursor.fetchall()]

    async def begin_command(self, *, key: tuple[str, str, str], digest: str, method: str) -> tuple[dict | None, bool]:
        """下发之前保留请求摘要；不保存参数、文件或结果内容。"""
        async with self.lock:
            async with self.connection.execute("SELECT * FROM commands WHERE grant_id=? AND session_id=? AND request_id=?", key) as cursor:
                row = await cursor.fetchone()
            if row is not None:
                return dict(row), False
            await self.connection.execute("DELETE FROM commands WHERE session_id IN (SELECT session_id FROM sessions WHERE json_extract(record,'$.state') IN ('CLOSED','FAILED','INTERRUPTED')) AND julianday(updated_at) < julianday('now','-1 day')")
            async with self.connection.execute("SELECT COUNT(*) FROM commands WHERE session_id=?", (key[1],)) as cursor:
                count = (await cursor.fetchone())[0]
            if count >= 10000:
                await self.connection.commit()
                return None, False
            now = datetime.now(UTC).isoformat()
            await self.connection.execute("INSERT INTO commands VALUES (?,?,?,?,?,'DISPATCHED','OUTCOME_UNKNOWN',NULL,?,?)", (*key, digest, method, now, now))
            await self.connection.commit()
            return {"grant_id": key[0], "session_id": key[1], "request_id": key[2], "digest": digest, "method": method, "status": "DISPATCHED", "execution_outcome": "OUTCOME_UNKNOWN", "error_code": None}, True

    async def command(self, *, key: tuple[str, str, str]) -> dict | None:
        async with self.lock:
            async with self.connection.execute("SELECT * FROM commands WHERE grant_id=? AND session_id=? AND request_id=?", key) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row is not None else None

    async def finish_command(self, *, key, status, outcome="OUTCOME_UNKNOWN", code=None):
        async with self.lock:
            await self.connection.execute("UPDATE commands SET status=?,execution_outcome=?,error_code=?,updated_at=? WHERE grant_id=? AND session_id=? AND request_id=?", (status, outcome, code, datetime.now(UTC).isoformat(), *key))
            await self.connection.commit()

    async def interrupt_commands(self):
        async with self.lock:
            await self.connection.execute("UPDATE commands SET status='UNKNOWN',execution_outcome='OUTCOME_UNKNOWN',error_code='RESULT_UNKNOWN' WHERE status IN ('DISPATCHED','ACCEPTED','RUNNING')")
            await self.connection.commit()

    @staticmethod
    def _grant(*, row) -> dict:
        record = dict(row)
        record["resource_ids"] = json.loads(record["resource_ids"]) if record["resource_ids"] is not None else None
        return record
