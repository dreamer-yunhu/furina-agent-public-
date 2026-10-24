"""T23-3 验收：POST /agent/decisions 调用 T20，归属/幂等/冲突/越权。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真实 FastAPI lifespan + 真实 SQLite 业务库 + 真实 checkpoint + Fake LLM。
# 不是 Mock：审批状态、decided_by/decided_at、任务状态都直接查库断言。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_t23_decision_api.py
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "desktop" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "core" / "src"))

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, AIMessageChunk  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, bool]] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    _results.append((label, ok))
    print(f"  [{PASS if ok else FAIL}] {label}" + (f"   {extra}" if extra else ""))


class FakeStream(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-stream"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls += 1
        message = (
            AIMessage(content="好的，",
                      tool_calls=[{"name": "write_file_tool",
                                   "args": {"file_path": "out.txt", "text": "approved!"},
                                   "id": "call_w1"}])
            if self.calls == 1 else AIMessage(content="done")
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            yield ChatGenerationChunk(message=AIMessageChunk(content="好"))
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "write_file_tool",
                                   "args": json.dumps({"file_path": "out.txt",
                                                       "text": "approved!"}),
                                   "id": "call_w1", "index": 0}],
            ))
        else:
            yield ChatGenerationChunk(message=AIMessageChunk(content="done"))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


class FakeTwoBatches(BaseChatModel):
    """第 1 次调用写 a.txt，第 2 次写 b.txt，第 3 次结束。"""

    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-two-batches"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._message())])

    def _message(self) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[
                {"name": "write_file_tool", "args": {"file_path": "a.txt", "text": "A"}, "id": "call_a"}
            ])
        if self.calls == 2:
            return AIMessage(content="", tool_calls=[
                {"name": "write_file_tool", "args": {"file_path": "b.txt", "text": "B"}, "id": "call_b"}
            ])
        return AIMessage(content="done")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._message()
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))
        for tool_call in message.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": tool_call["name"],
                                   "args": json.dumps(tool_call["args"]),
                                   "id": tool_call["id"], "index": 0}],
            ))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


def parse_sse(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def approval_rows(db: Path):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT id, tool_call_id, approval_status, decided_by, decided_at, "
            "tool_execution_status FROM approval_request"
        ).fetchall()
    finally:
        con.close()


def rows_for_execution(db: Path, execution_id: str):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT id, tool_call_id, approval_status, decided_by, decided_at, "
            "tool_execution_status FROM approval_request WHERE execution_id=?",
            (uuid.UUID(execution_id).hex,),
        ).fetchall()
    finally:
        con.close()


def status_for_execution(db: Path, execution_id: str):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT t.status, e.status FROM agent_task t "
            "JOIN agent_execution e ON e.task_id = t.id WHERE e.id=?",
            (uuid.UUID(execution_id).hex,),
        ).fetchall()
    finally:
        con.close()


def task_rows(db: Path):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT t.status, e.status FROM agent_task t "
            "JOIN agent_execution e ON e.task_id = t.id"
        ).fetchall()
    finally:
        con.close()


def main() -> None:
    workdir = ROOT / "_smoke_tmp" / "t23_decision_api"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    (workdir / "data").mkdir(parents=True)
    box = workdir / "sandbox"
    box.mkdir()
    os.chdir(workdir)

    from fastapi.testclient import TestClient  # noqa: E402

    from furina_core.config import settings  # noqa: E402
    import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
    from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
    from furina_desktop.main import create_app  # noqa: E402

    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)
    coder_mod.llm_with_tools = FakeStream()

    db = workdir / "data" / "furina.db"
    app = create_app()
    with TestClient(app) as client:
        print("=== 1. create thread + risky run ===")
        thread_id = client.post("/agent/threads", json={"title": "t23-3"}).json()["id"]
        r = client.post("/agent", json={"user_input": "write it", "chat_thread_id": thread_id})
        check("POST /agent 200", r.status_code == 200, str(r.status_code))
        events = parse_sse(r.text)
        approval_evt = next(e for e in events if e["type"] == "approval_required")
        req0 = approval_evt["review"]["requests"][0]
        approval_id = req0["approval_id"]
        rows = approval_rows(db)
        check("one PENDING row", len(rows) == 1 and rows[0][2] == "PENDING", str(rows))

        print("\n=== 2. approve via /agent/decisions ===")
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread_id,
            "decisions": [{"approval_id": approval_id, "tool_call_id": "call_w1",
                           "action": "approve", "reason": None}],
        })
        check("200 APPLIED", r.status_code == 200 and r.json()["results"][0]["outcome"] == "APPLIED",
              f"{r.status_code} {r.text[:120]}")
        rows = approval_rows(db)
        check("DB APPROVED", rows[0][2] == "APPROVED", str(rows[0]))
        check("decided_by persisted", bool(rows[0][3]), str(rows[0]))
        check("decided_at persisted", bool(rows[0][4]), str(rows[0]))
        first_decided_at = rows[0][4]
        check("decisions do NOT resume graph",
              task_rows(db) == [("WAITING_APPROVAL", "WAITING_APPROVAL")], str(task_rows(db)))

        print("\n=== 3. duplicate approve → IDEMPOTENT, no timestamp change ===")
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread_id,
            "decisions": [{"approval_id": approval_id, "action": "approve"}],
        })
        check("200 IDEMPOTENT", r.status_code == 200 and r.json()["results"][0]["outcome"] == "IDEMPOTENT",
              f"{r.status_code} {r.text[:120]}")
        rows = approval_rows(db)
        check("decided_at unchanged", rows[0][4] == first_decided_at)

        print("\n=== 4. opposite decision → 409, no overwrite ===")
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread_id,
            "decisions": [{"approval_id": approval_id, "action": "reject"}],
        })
        check("409 CONFLICT", r.status_code == 409 and
              r.json()["detail"]["results"][0]["outcome"] == "CONFLICT",
              f"{r.status_code} {r.text[:160]}")
        rows = approval_rows(db)
        check("DB still APPROVED", rows[0][2] == "APPROVED", str(rows[0]))

        print("\n=== 5. forged approval_id → 404 ===")
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread_id,
            "decisions": [{"approval_id": str(uuid.uuid4()), "action": "approve"}],
        })
        check("404 on forged id", r.status_code == 404, f"{r.status_code} {r.text[:120]}")
        check("DB unchanged", approval_rows(db)[0][2] == "APPROVED")

        print("\n=== 6. missing both identifiers → 422 ===")
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread_id,
            "decisions": [{"action": "approve"}],
        })
        check("422 on missing identifiers", r.status_code == 422, str(r.status_code))

        print("\n=== 7. thread without active execution → 409 ===")
        other = client.post("/agent/threads", json={"title": "empty"}).json()["id"]
        r = client.post("/agent/decisions", json={
            "chat_thread_id": other,
            "decisions": [{"approval_id": approval_id, "action": "approve"}],
        })
        check("409 no active execution", r.status_code == 409, f"{r.status_code} {r.text[:80]}")

        print("\n=== 8. resume uses persisted decision → graph completes ===")
        r = client.post("/agent/resume", json={
            "chat_thread_id": thread_id,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": approval_id, "tool_call_id": "call_w1",
                                      "action": "approve", "reason": None}]},
        })
        check("POST /agent/resume 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        events = parse_sse(r.text)
        check("done completed", events[-1] == {"type": "done", "status": "completed"}, str(events[-1]))
        check("file written", (box / "out.txt").is_file())
        check("task/execution COMPLETED", task_rows(db) == [("COMPLETED", "COMPLETED")], str(task_rows(db)))
        rows = approval_rows(db)
        check("approval still APPROVED", rows[0][2] == "APPROVED", str(rows[0]))
        check("tool status SUCCEEDED (T23-4)", rows[0][5] == "SUCCEEDED", str(rows[0]))

        print("\n=== 9. reject via decisions, then resume: tool not executed ===")
        coder_mod.llm_with_tools = FakeStream()
        thread2 = client.post("/agent/threads", json={"title": "reject"}).json()["id"]
        r = client.post("/agent", json={"user_input": "write it", "chat_thread_id": thread2})
        events = parse_sse(r.text)
        rej_id = next(e for e in events if e["type"] == "approval_required")["review"]["requests"][0]["approval_id"]
        (box / "out.txt").unlink(missing_ok=True)
        r = client.post("/agent/decisions", json={
            "chat_thread_id": thread2,
            "decisions": [{"approval_id": rej_id, "tool_call_id": "call_w1",
                           "action": "reject", "reason": "不允许"}],
        })
        check("reject APPLIED", r.status_code == 200 and r.json()["results"][0]["outcome"] == "APPLIED",
              f"{r.status_code} {r.text[:120]}")
        r = client.post("/agent/resume", json={
            "chat_thread_id": thread2,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": rej_id, "tool_call_id": "call_w1",
                                      "action": "reject", "reason": "不允许"}]},
        })
        check("reject resume 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        check("rejected file not written", not (box / "out.txt").exists())
        rej_row = [row for row in approval_rows(db) if str(row[0]) == uuid.UUID(rej_id).hex][0]
        check("approval REJECTED", rej_row[2] == "REJECTED", str(rej_row))
        check("reject run completed", task_rows(db)[-1] == ("COMPLETED", "COMPLETED"), str(task_rows(db)))

        print("\n=== 10. 同一 Execution 第二批审批（批次范围生效） ===")
        coder_mod.llm_with_tools = FakeTwoBatches()
        t2 = client.post("/agent/threads", json={"title": "two-batches"}).json()["id"]
        r = client.post("/agent", json={"user_input": "two writes", "chat_thread_id": t2})
        ev1 = next(e for e in parse_sse(r.text) if e["type"] == "approval_required")
        a1 = ev1["review"]["requests"][0]["approval_id"]
        d1 = client.post("/agent/decisions", json={
            "chat_thread_id": t2,
            "decisions": [{"approval_id": a1, "tool_call_id": "call_a", "action": "approve"}],
        })
        exec2 = d1.json()["execution_id"]
        r = client.post("/agent/resume", json={
            "chat_thread_id": t2,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": a1, "tool_call_id": "call_a", "action": "approve"}]},
        })
        check("first batch resume 200", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
        ev2 = [e for e in parse_sse(r.text) if e["type"] == "approval_required"]
        check("second batch interrupts", len(ev2) == 1, str(ev2)[:120])
        a2 = ev2[0]["review"]["requests"][0]["approval_id"] if ev2 else None
        rows = rows_for_execution(db, exec2)
        check("two approval rows", len(rows) == 2, str(rows))
        status_by_id = {str(row[0]): row[2:6] for row in rows}
        check("first batch SUCCEEDED", status_by_id.get(uuid.UUID(a1).hex, ("",))[3:] == ("SUCCEEDED",),
              str(status_by_id.get(uuid.UUID(a1).hex)))
        check("second batch PENDING", status_by_id.get(uuid.UUID(a2).hex, ("",))[0] == "PENDING" if a2 else False,
              str(status_by_id.get(uuid.UUID(a2).hex)) if a2 else "no a2")
        client.post("/agent/decisions", json={
            "chat_thread_id": t2,
            "decisions": [{"approval_id": a2, "tool_call_id": "call_b", "action": "approve"}],
        })
        r = client.post("/agent/resume", json={
            "chat_thread_id": t2,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": a2, "tool_call_id": "call_b", "action": "approve"}]},
        })
        check("second batch resume 200", r.status_code == 200, f"{r.status_code} {r.text[:160]}")
        check("both files written", (box / "a.txt").is_file() and (box / "b.txt").is_file())
        rows = rows_for_execution(db, exec2)
        check("both SUCCEEDED", all(row[5] == "SUCCEEDED" for row in rows), str(rows))

        print("\n=== 11. 参数快照被篡改：preflight 拒绝且不调图 ===")
        coder_mod.llm_with_tools = FakeStream()
        t3 = client.post("/agent/threads", json={"title": "tamper"}).json()["id"]
        r = client.post("/agent", json={"user_input": "write it", "chat_thread_id": t3})
        ev = next(e for e in parse_sse(r.text) if e["type"] == "approval_required")
        aid = ev["review"]["requests"][0]["approval_id"]
        d3 = client.post("/agent/decisions", json={
            "chat_thread_id": t3,
            "decisions": [{"approval_id": aid, "tool_call_id": "call_w1", "action": "approve"}],
        })
        exec3 = d3.json()["execution_id"]
        import hashlib
        bad_args = '{"file_path":"out.txt","text":"tampered"}'
        bad_hash = hashlib.sha256(bad_args.encode("utf-8")).hexdigest()
        con = sqlite3.connect(db)
        con.execute("UPDATE approval_request SET args_json=?, args_hash=? WHERE id=?",
                    (bad_args, bad_hash, uuid.UUID(aid).hex))
        con.commit(); con.close()
        r = client.post("/agent/resume", json={
            "chat_thread_id": t3,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": aid, "tool_call_id": "call_w1", "action": "approve"}]},
        })
        check("409 args_mismatch", r.status_code == 409 and
              r.json()["detail"].get("code") == "args_mismatch",
              f"{r.status_code} {r.text[:160]}")
        check("tampered tool not executed", not (box / "out.txt").exists())
        check("state still WAITING_APPROVAL",
              status_for_execution(db, exec3) == [("WAITING_APPROVAL", "WAITING_APPROVAL")],
              str(status_for_execution(db, exec3)))

        print("\n=== 12. 删除 checkpoint：拒绝恢复（state_mismatch） ===")
        con = sqlite3.connect(workdir / "data" / "checkpoints.sqlite")
        con.execute("DELETE FROM writes")
        con.execute("DELETE FROM checkpoints")
        con.commit(); con.close()
        r = client.post("/agent/resume", json={
            "chat_thread_id": t3,
            "review": {"type": "review_decision",
                       "decisions": [{"approval_id": aid, "tool_call_id": "call_w1", "action": "approve"}]},
        })
        check("409 state_mismatch after checkpoint loss",
              r.status_code == 409 and r.json()["detail"].get("code") == "state_mismatch",
              f"{r.status_code} {r.text[:160]}")

    ok = sum(1 for _, o in _results if o)
    print(f"\n{ok}/{len(_results)} passed")
    if ok != len(_results):
        print("failed:")
        for label, o in _results:
            if not o:
                print("  -", label)
        sys.exit(1)


if __name__ == "__main__":
    main()
