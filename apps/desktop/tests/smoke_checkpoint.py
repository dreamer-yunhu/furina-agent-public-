"""SQLite checkpoint store 的冒烟测试 —— 纯标准库断言，不依赖 pytest。

跑法（在仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_checkpoint.py

它验的是"这个实现真的能用"，不是"代码长得对"：
    1. open() 建出 db 文件
    2. setup() 后三张表存在
    3. 读不存在的 thread 返回 None（不抛异常）
    4. 写入 → 读回来，且 config 里有 checkpoint_id
    5. adelete_thread 后记录清零
    6. close() 后文件能删掉（Windows 文件锁）
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

# 让脚本能直接跑（不必先装包）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages" / "core" / "src"))

from furina_desktop.storage import SqliteCheckpointStore  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


def tables(db: Path) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def count(db: Path, table: str, thread_id: str) -> int:
    con = sqlite3.connect(db)
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table} WHERE thread_id=?", (thread_id,)).fetchone()[0]
    finally:
        con.close()


async def main() -> None:
    # ⚠️ 用工作区内的目录，**不用 tempfile.mkdtemp()**。
    #    实测：DSH 沙箱下 `%TEMP%\dsh-*\` 里的目录**存在但写不进去**，
    #    会让 sqlite3 报 `unable to open database file` ——
    #    那是环境限制，不是本模块的 bug。用仓库内的路径可以绕开，
    #    也让失败更可诊断（你能直接去看那个文件）。
    tmpdir = Path(__file__).resolve().parents[3] / "_smoke_tmp"
    if tmpdir.exists():
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)
    tmpdir.mkdir(parents=True, exist_ok=True)
    db = tmpdir / "nested" / "checkpoints.sqlite"  # 故意用不存在的子目录，验 mkdir

    print("=== SqliteCheckpointStore ===")
    store = SqliteCheckpointStore(db)

    # 1) 未 open 就用 → 应给出可操作的错误，而不是 AttributeError
    try:
        await store.aget_tuple({"configurable": {"thread_id": "x"}})
        check("未 open 就调用应报错", False, "没报错")
    except RuntimeError as e:
        check("未 open 就调用给出清晰错误", "open()" in str(e))

    # 2) open() 建文件（含父目录）
    await store.open()
    check("open() 创建了 db 文件（含父目录）", db.is_file(), str(db.relative_to(tmpdir)))

    # 3) setup() 建表
    # ⚠️ 表名以**源码为准**（我第一版断言用的是 PostgreSQL saver 的表名，错了）：
    #    实测 `langgraph/checkpoint/sqlite/aio.py` 的 DDL 只有两张表 ——
    #        checkpoints (thread_id, checkpoint_ns, checkpoint_id, ..., checkpoint, metadata)
    #        writes      (thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, ...)
    #    PG 版是**三张**（多一个 checkpoint_blobs），SQLite 版没有 blobs ——
    #    因为 SQLite 可以直接把 blob 存在行里，不需要拆表。
    await store.setup()
    t = tables(db)
    need = {"checkpoints", "writes"}
    check("setup() 建出两张表（SQLite 版：checkpoints + writes）", need.issubset(t), f"实得 {sorted(t)}")

    # 4) 读不存在的 thread → None
    got = await store.aget_tuple({"configurable": {"thread_id": "no-such-thread"}})
    check("读不存在的 thread 返回 None", got is None, f"实得 {got!r}")

    # 5) 写入 → 读回
    #    构造最小合法 checkpoint：库要求 id / channel_values / channel_versions /
    #    versions_seen / ts 等字段
    cfg = {"configurable": {"thread_id": "t-1", "checkpoint_ns": ""}}
    checkpoint = {
        "v": 1,
        "id": "cp-0001",
        "ts": "2026-01-01T00:00:00+00:00",
        "channel_values": {"messages": []},
        "channel_versions": {"messages": "1"},
        "versions_seen": {},
        "pending_sends": [],
    }
    new_cfg = await store.aput(cfg, checkpoint, {"source": "input", "step": 0}, {"messages": "1"})
    new_id = new_cfg.get("configurable", {}).get("checkpoint_id")
    check("aput 返回带 checkpoint_id 的 config", bool(new_id), f"checkpoint_id={new_id!r}")

    # ⚠️ 注意：`aput` 返回的 checkpoint_id **就是传入的 checkpoint["id"]**
    #    （源码 aio.py:557 `"checkpoint_id": checkpoint["id"]`），
    #    不是库另外生成的。所以下面断言它等于 "cp-0001"。
    check("返回的 checkpoint_id == 传入的 checkpoint['id']", new_id == "cp-0001")

    back = await store.aget_tuple(new_cfg)
    check("写入后能读回", back is not None)
    if back is not None:
        # ⚠️ `back` 是 `CheckpointTuple`（dataclass），而 `back.checkpoint` 是 **dict**。
        #    我第一版写成 `getattr(back.checkpoint, "id", None)` —— 对 dict 永远返回 None，
        #    于是断言必然失败。**字典要用 ["id"] 或 .get("id")**。
        #    （这与 docs/NOTES.md 里反复记的"对象 vs 字典"是同一个病根。）
        check("读回的 checkpoint 是 dict", isinstance(back.checkpoint, dict))
        check("读回的 checkpoint['id'] 一致", back.checkpoint.get("id") == "cp-0001")
        check("读回的 metadata 一致", back.metadata.get("step") == 0)

    # 6) 中间写入
    await store.aput_writes(new_cfg, [("messages", ["x"])], task_id="task-1")
    check("aput_writes 落库", count(db, "writes", "t-1") >= 1)

    # 7) alist 能迭代
    n = 0
    async for _ in store.alist(cfg):
        n += 1
    check("alist 可迭代且至少 1 条", n >= 1, f"实得 {n} 条")

    # 8) 删 thread（两张表都要清干净 —— 这是 PLAN 里那条"0 残留"验收）
    await store.adelete_thread("t-1")
    left = sum(count(db, tbl, "t-1") for tbl in ("checkpoints", "writes"))
    check("adelete_thread 后无残留（checkpoints + writes）", left == 0, f"残留 {left} 条")

    # 9) close() 后文件可删（Windows 文件锁）
    await store.close()
    try:
        db.unlink()
        check("close() 后文件可删（无句柄残留）", True)
    except PermissionError as e:
        check("close() 后文件可删（无句柄残留）", False, str(e))

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} 通过")
    if ok != len(_results):
        print("失败项:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
