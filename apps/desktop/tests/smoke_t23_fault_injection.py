"""T23-5 故障注入：部分决定、陈旧执行、图/工具/checkpoint 故障、并发恢复。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 类型：真实 FastAPI lifespan + 真实 SQLite + 真实 checkpoint + Fake LLM。
# 故障通过替换 graph.astream / graph.aget_state / tool_node 注入；
# 不是 Mock 掉业务服务。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_t23_fault_injection.py
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
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


class FakeOne(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-one"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._msg())])

    def _msg(self) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[
                {"name": "write_file_tool", "args": {"file_path": "out.txt", "text": "OK"},
                 "id": "call_w1"}])
        return AIMessage(content="done")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._msg()
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))
        for tc in message.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": tc["name"], "args": json.dumps(tc["args"]),
                                   "id": tc["id"], "index": 0}],
            ))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


class FakeTwo(BaseChatModel):
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-two"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._msg())])

    def _msg(self) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            return AIMessage(content="", tool_calls=[
                {"name": "write_file_tool", "args": {"file_path": "a.txt", "text": "A"}, "id": "call_a"},
                {"name": "write_file_tool", "args": {"file_path": "b.txt", "text": "B"}, "id": "call_b"},
            ])
        return AIMessage(content="done")

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        message = self._msg()
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))
        for tc in message.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": tc["name"], "args": json.dumps(tc["args"]),
                                   "id": tc["id"], "index": 0}],
            ))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


def parse_sse(text: str) -> list[dict]:
    return [json.loads(line[len("data: "):])
            for line in text.splitlines() if line.startswith("data: ")]


def approval_ids(events: list[dict]) -> list[dict]:
    ev = next(e for e in events if e["type"] == "approval_required")
    return ev["review"]["requests"]


def rows(db: Path, thread_id: str):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT id, tool_call_id, approval_status, tool_execution_status "
            "FROM approval_request WHERE task_id IN "
            "(SELECT id FROM agent_task WHERE thread_id=?)", (uuid.UUID(thread_id).hex,)
        ).fetchall()
    finally:
        con.close()


def states(db: Path, thread_id: str):
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT t.status, e.status FROM agent_task t "
            "JOIN agent_execution e ON e.task_id=t.id WHERE t.thread_id=?",
            (uuid.UUID(thread_id).hex,),
        ).fetchall()
    finally:
        con.close()


def new_thread(client) -> str:
    return client.post("/agent/threads", json={"title": "fault"}).json()["id"]


def run_risky(client, coder_mod, model, *, title="fault"):
    coder_mod.llm_with_tools = model
    thread_id = new_thread(client)
    r = client.post("/agent", json={"user_input": "write", "chat_thread_id": thread_id})
    assert r.status_code == 200, r.text
    return thread_id, approval_ids(parse_sse(r.text))


def decide(client, thread_id, item, action="approve"):
    return client.post("/agent/decisions", json={
        "chat_thread_id": thread_id,
        "decisions": [{"approval_id": item["approval_id"],
                       "tool_call_id": item["tool_call_id"],
                       "action": action, "reason": None}],
    })


def resume_body(thread_id, items):
    return {
        "chat_thread_id": thread_id,
        "review": {"type": "review_decision", "decisions": [
            {"approval_id": i["approval_id"], "tool_call_id": i["tool_call_id"],
             "action": "approve", "reason": None} for i in items
        ]},
    }


def main() -> None:
    workdir = ROOT / "_smoke_tmp" / "t23_fault"
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
    app = create_app()
    db = workdir / "data" / "furina.db"

    with TestClient(app) as client:
        print("\n=== 1. 同批两个审批只决定一个：resume 409 ===")
        t1, items1 = run_risky(client, coder_mod, FakeTwo(), title="partial")
        check("setup interrupted", len(items1) == 2, str(len(items1)))
        if len(items1) == 2:
            decide(client, t1, items1[0])
            r = client.post("/agent/resume", json=resume_body(t1, [items1[0]]))
            check("409 decision_mismatch", r.status_code == 409, f"{r.status_code} {r.text[:120]}")
            rs = rows(db, t1)
            check("one APPROVED one PENDING",
                  sorted(row[2] for row in rs) == ["APPROVED", "PENDING"], str(rs))
            check("no file written", not (box / "a.txt").exists() and not (box / "b.txt").exists())
            bad_uuid = client.post("/agent/resume", json={
                "chat_thread_id": t1,
                "review": {"type": "review_decision", "decisions": [
                    {"approval_id": "not-a-uuid", "tool_call_id": items1[0]["tool_call_id"],
                     "action": "approve"},
                    {"approval_id": items1[1]["approval_id"], "tool_call_id": items1[1]["tool_call_id"],
                     "action": "approve"},
                ]},
            })
            check("422 invalid approval_id", bad_uuid.status_code == 422,
                  f"{bad_uuid.status_code} {bad_uuid.text[:100]}")

        print("\n=== 2. 跨执行 approval_id：404 ===")
        t2, items2 = run_risky(client, coder_mod, FakeOne(), title="cross-1")
        # t1 的活动执行仍然存在，用 t2 的 approval 去 t1 上决定
        r = decide(client, t1, items2[0]) if items2 else None
        check("404 scope mismatch", r is not None and r.status_code == 404,
              f"{r.status_code if r else None} {r.text[:100] if r else ''}")

        print("\n=== 3. 认领后崩溃（RUNNING）：resume 拒绝 ===")
        t3, items3 = run_risky(client, coder_mod, FakeOne(), title="stale")
        decide(client, t3, items3[0])
        con = sqlite3.connect(db)
        con.execute("UPDATE approval_request SET tool_execution_status='RUNNING' WHERE id=?",
                    (uuid.UUID(items3[0]["approval_id"]).hex,))
        con.commit(); con.close()
        r = client.post("/agent/resume", json=resume_body(t3, items3))
        check("409 ALREADY_EXECUTED", r.status_code == 409 and
              r.json()["detail"].get("code") == "ALREADY_EXECUTED",
              f"{r.status_code} {r.text[:160]}")
        check("no tool executed", not (box / "out.txt").exists())

        print("\n=== 4. 图恢复失败：SUSPENDED，不重放 ===")
        t4, items4 = run_risky(client, coder_mod, FakeOne(), title="graph-fail")
        decide(client, t4, items4[0])
        graph = app.state.graph
        original_stream = graph.astream

        async def _boom(*args, **kwargs):
            raise RuntimeError("injected graph failure")
            yield  # pragma: no cover

        graph.astream = _boom
        try:
            r = client.post("/agent/resume", json=resume_body(t4, items4))
        finally:
            graph.astream = original_stream
        ev = parse_sse(r.text) if r.status_code == 200 else []
        check("SSE error + failed", any(e["type"] == "error" for e in ev) and
              ev[-1].get("status") == "failed" if ev else False, str(ev[-1]) if ev else r.text[:120])
        check("execution SUSPENDED", states(db, t4) == [("SUSPENDED", "SUSPENDED")],
              str(states(db, t4)))
        check("no tool executed", not (box / "out.txt").exists())

        print("\n=== 5. 认领后工具崩溃：UNKNOWN + FAILED ===")
        t5, items5 = run_risky(client, coder_mod, FakeOne(), title="tool-fail")
        decide(client, t5, items5[0])

        class BoomTool:
            async def ainvoke(self, payload):
                raise RuntimeError("injected tool failure")

        original_tool = coder_mod.tool_node
        coder_mod.tool_node = BoomTool()
        try:
            r = client.post("/agent/resume", json=resume_body(t5, items5))
        finally:
            coder_mod.tool_node = original_tool
        check("resume streamed error", r.status_code == 200 and
              any(e["type"] == "error" for e in parse_sse(r.text)), f"{r.status_code} {r.text[:120]}")
        rs = rows(db, t5)
        check("tool UNKNOWN", rs and rs[0][3] == "UNKNOWN", str(rs))
        check("execution FAILED", states(db, t5) == [("FAILED", "FAILED")],
              str(states(db, t5)))
        check("file not written", not (box / "out.txt").exists())

        print("\n=== 6. checkpoint 读取失败：503 ===")
        t6, items6 = run_risky(client, coder_mod, FakeOne(), title="cp-fail")
        decide(client, t6, items6[0])
        original_get = graph.aget_state

        async def _bad_get(*args, **kwargs):
            raise RuntimeError("injected checkpoint read failure")

        graph.aget_state = _bad_get
        try:
            r = client.post("/agent/resume", json=resume_body(t6, items6))
        finally:
            graph.aget_state = original_get
        check("503 checkpoint_unavailable", r.status_code == 503 and
              r.json()["detail"].get("code") == "checkpoint_unavailable",
              f"{r.status_code} {r.text[:160]}")
        check("state untouched", states(db, t6) == [("WAITING_APPROVAL", "WAITING_APPROVAL")],
              str(states(db, t6)))

        print("\n=== 7. 并发恢复：只有一个成功 ===")
        t7, items7 = run_risky(client, coder_mod, FakeOne(), title="concurrent")
        decide(client, t7, items7[0])
        body = resume_body(t7, items7)
        results: list[int] = []
        lock = threading.Lock()

        def _resume():
            resp = client.post("/agent/resume", json=body)
            with lock:
                results.append(resp.status_code)

        threads = [threading.Thread(target=_resume) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("exactly one 200", results.count(200) == 1, str(results))
        check("one request rejected", any(code != 200 for code in results), str(results))
        check("file written once", (box / "out.txt").is_file())

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
