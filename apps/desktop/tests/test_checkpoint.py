# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""SQLite checkpoint store（由 smoke_checkpoint.py 原生化）。

复核重点：
    1. 表名以**源码**为准：SQLite 版只有 `checkpoints` + `writes` 两张表，
       没有 PG 版的 `checkpoint_blobs`（SQLite 直接把 blob 存在行里）。
    2. `aput` 返回的 checkpoint_id 就是传入的 `checkpoint["id"]`，不是另生成的。
    3. `CheckpointTuple.checkpoint` 是 **dict**，要用 `.get()`，不能 getattr。
    4. `close()` 之后文件必须可删 —— Windows 上有文件句柄残留就删不掉。
"""

from __future__ import annotations

import asyncio
import sqlite3

from furina_desktop.storage import SqliteCheckpointStore


def tables(db_path) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {
            row[0]
            for row in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        con.close()


def count(db_path, table: str, thread_id: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM {table} WHERE thread_id=?", (thread_id,)
        ).fetchone()[0]
    finally:
        con.close()


def test_sqlite_checkpoint_store_lifecycle(tmp_path):
    # 故意用不存在的子目录，顺带验证 open() 会建父目录
    db_path = tmp_path / "nested" / "checkpoints.sqlite"

    async def scenario() -> None:
        store = SqliteCheckpointStore(db_path)

        # 1) 未 open 就用 → 可操作的错误，而不是 AttributeError
        try:
            await store.aget_tuple({"configurable": {"thread_id": "x"}})
            raise AssertionError("未 open 就调用应当报错")
        except RuntimeError as error:
            assert "open()" in str(error), error

        # 2) open() 建文件（含父目录）
        await store.open()
        assert db_path.is_file(), db_path

        # 3) setup() 建表：SQLite 版只有两张
        await store.setup()
        existing = tables(db_path)
        assert {"checkpoints", "writes"}.issubset(existing), sorted(existing)

        # 4) 读不存在的 thread → None
        assert (
            await store.aget_tuple({"configurable": {"thread_id": "no-such-thread"}})
            is None
        )

        # 5) 写入 → 读回
        config = {"configurable": {"thread_id": "t-1", "checkpoint_ns": ""}}
        checkpoint = {
            "v": 1,
            "id": "cp-0001",
            "ts": "2026-01-01T00:00:00+00:00",
            "channel_values": {"messages": []},
            "channel_versions": {"messages": "1"},
            "versions_seen": {},
            "pending_sends": [],
        }
        new_config = await store.aput(
            config, checkpoint, {"source": "input", "step": 0}, {"messages": "1"}
        )
        assert new_config["configurable"]["checkpoint_id"] == "cp-0001"

        back = await store.aget_tuple(new_config)
        assert back is not None
        assert isinstance(back.checkpoint, dict)
        assert back.checkpoint.get("id") == "cp-0001"
        assert back.metadata.get("step") == 0

        # 6) 中间写入落库
        await store.aput_writes(new_config, [("messages", ["x"])], task_id="task-1")
        assert count(db_path, "writes", "t-1") >= 1

        # 7) alist 可迭代
        listed = [item async for item in store.alist(config)]
        assert len(listed) >= 1

        # 8) 删 thread：两张表都不留残留
        await store.adelete_thread("t-1")
        leftover = sum(
            count(db_path, table, "t-1") for table in ("checkpoints", "writes")
        )
        assert leftover == 0, f"残留 {leftover} 条"

        # 9) close() 后文件可删（Windows 文件锁）
        await store.close()
        db_path.unlink()  # 删不掉会抛 PermissionError，测试自然失败

    asyncio.run(scenario())
