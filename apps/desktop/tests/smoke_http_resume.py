"""HTTP 层审批链路验收：POST /agent + POST /agent/resume 的 200 / 404 / 409。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：用 FastAPI TestClient 跑**真 lifespan**（真 SQLite 业务库 + 真
# checkpoint 文件），只把 LLM 换成分块输出的假模型。工作目录切到临时目录，
# 避免污染仓库根的 data/。

跑法（仓库根）：
    .venv-build\\Scripts\\python.exe apps\\desktop\\tests\\smoke_http_resume.py

覆盖：
    1. POST /agent 返回 SSE，含 token / approval_required / done=interrupted
    2. 决定与待审项不匹配 → 409
    3. 未知线程 → 404
    4. 非挂起线程 → 409
    5. 正确决定 → 200，文件落盘，done=completed
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
            for piece in ("好", "的", "，"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
            yield ChatGenerationChunk(message=AIMessageChunk(
                content="",
                tool_call_chunks=[{"name": "write_file_tool",
                                   "args": json.dumps({"file_path": "out.txt",
                                                       "text": "approved!"}),
                                   "id": "call_w1", "index": 0}],
            ))
        else:
            for piece in ("do", "ne"):
                yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        yield ChatGenerationChunk(message=AIMessageChunk(content=""))


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def main() -> None:
    workdir = ROOT / "_smoke_tmp" / "http_resume"
    if workdir.exists():
        shutil.rmtree(workdir, ignore_errors=True)
    (workdir / "data").mkdir(parents=True)
    box = workdir / "sandbox"
    box.mkdir()

    # 必须在 create_app 之前切目录：两个 SQLite 路径都是相对 CWD 的
    os.chdir(workdir)

    from fastapi.testclient import TestClient  # noqa: E402

    from furina_core.config import settings  # noqa: E402
    import furina_desktop.agent.nodes.coder as coder_mod  # noqa: E402
    from furina_desktop.agent.tools.registry import read_file_tool, write_file_tool  # noqa: E402
    from furina_desktop.main import create_app  # noqa: E402

    settings.sandbox_root = box
    read_file_tool.root_dir = str(box)
    write_file_tool.root_dir = str(box)
    from _t23_testkit import install_intent  # Stage A：主管意图节点也要替身
    install_intent("CODE")
    coder_mod.llm_with_tools = FakeStream()

    app = create_app()

    with TestClient(app) as client:
        print("=== 1. create thread + first run ===")
        r = client.post("/agent/threads", json={"title": "smoke"})
        check("thread created", r.status_code == 200, str(r.status_code))
        thread_id = r.json()["id"]

        r = client.post("/agent", json={"user_input": "write it", "chat_thread_id": thread_id})
        check("POST /agent 200", r.status_code == 200, str(r.status_code))
        check("SSE content-type", r.headers["content-type"].startswith("text/event-stream"))
        events = parse_sse(r.text)
        types = [e["type"] for e in events]
        check("token frames present", "token" in types, str(types))
        check("approval_required present", "approval_required" in types)
        check("first run ends interrupted", events[-1] == {"type": "done", "status": "interrupted"})
        approval = next(e for e in events if e["type"] == "approval_required")
        check("approval has interrupt_id", bool(approval["interrupt_id"]))

        # T23：图中断必须对应真实的审批行与 WAITING_APPROVAL 状态。
        con = sqlite3.connect(workdir / "data" / "furina.db")
        rows = con.execute(
            "SELECT id, tool_call_id, approval_status, tool_execution_status "
            "FROM approval_request"
        ).fetchall()
        statuses = con.execute(
            "SELECT t.status, e.status FROM agent_task t "
            "JOIN agent_execution e ON e.task_id = t.id"
        ).fetchall()
        con.close()
        check("DB has one approval row", len(rows) == 1, str(rows))
        check("approval bound to tool_call_id", rows and rows[0][1] == "call_w1", str(rows))
        check("approval PENDING", rows and rows[0][2] == "PENDING", str(rows))
        check("tool NOT_STARTED", rows and rows[0][3] == "NOT_STARTED", str(rows))
        req0 = (approval.get("review") or {}).get("requests", [{}])[0]
        same_id = bool(rows and req0.get("approval_id")) and (
            uuid.UUID(req0["approval_id"]) == uuid.UUID(str(rows[0][0]))
        )
        check("payload approval_id = DB id", same_id,
              f"{req0.get('approval_id')} / {rows[0][0] if rows else None}")
        check("task/execution WAITING_APPROVAL",
              statuses == [("WAITING_APPROVAL", "WAITING_APPROVAL")], str(statuses))

        print("\n=== 2. mismatched decision → 409 ===")
        r = client.post("/agent/resume", json={
            "chat_thread_id": thread_id,
            "review": {"type": "review_decision",
                       "decisions": [{"tool_call_id": "forged", "action": "approve", "reason": None}]},
        })
        check("409 on forged decision", r.status_code == 409, f"{r.status_code} {r.text[:80]}")
        check("file not written", not (box / "out.txt").exists())

        print("\n=== 3. unknown thread → 404 ===")
        r = client.post("/agent/resume", json={
            "chat_thread_id": str(uuid.uuid4()),
            "review": {"decisions": [{"tool_call_id": "call_w1", "action": "approve"}]},
        })
        check("404 on unknown thread", r.status_code == 404, str(r.status_code))

        print("\n=== 4. not-suspended thread → 409 ===")
        other = client.post("/agent/threads", json={"title": "other"}).json()["id"]
        r = client.post("/agent/resume", json={
            "chat_thread_id": other,
            "review": {"decisions": [{"tool_call_id": "call_w1", "action": "approve"}]},
        })
        check("409 on not suspended", r.status_code == 409, f"{r.status_code} {r.text[:80]}")

        print("\n=== 5. correct decision → 200 ===")
        r = client.post("/agent/resume", json={
            "chat_thread_id": thread_id,
            "review": {"type": "review_decision",
                       "decisions": [{"tool_call_id": "call_w1", "action": "approve", "reason": None}]},
        })
        check("POST /agent/resume 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        events = parse_sse(r.text)
        check("resume ends completed",
              events[-1] == {"type": "done", "status": "completed"}, str(events[-1]))
        check("file written", (box / "out.txt").is_file())
        check("file content correct",
              (box / "out.txt").read_text(encoding="utf-8") == "approved!")
        con = sqlite3.connect(workdir / "data" / "furina.db")
        final = con.execute(
            "SELECT t.status, e.status FROM agent_task t "
            "JOIN agent_execution e ON e.task_id = t.id"
        ).fetchall()
        decided = con.execute(
            "SELECT approval_status, decided_by, decided_at FROM approval_request"
        ).fetchall()
        con.close()
        check("task/execution COMPLETED after resume",
              final == [("COMPLETED", "COMPLETED")], str(final))
        check("approval APPROVED after resume",
              len(decided) == 1 and decided[0][0] == "APPROVED" and bool(decided[0][1]) and bool(decided[0][2]),
              str(decided))

        print("\n=== 6. replaying the same approval → 409 ===")
        r = client.post("/agent/resume", json={
            "chat_thread_id": thread_id,
            "review": {"decisions": [{"tool_call_id": "call_w1", "action": "approve"}]},
        })
        check("409 after already resumed", r.status_code == 409, str(r.status_code))

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
