# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""桌面版 HTTP 接口契约测试（pytest）。

为什么要有这份测试：
    前端是按后端契约写的，之前却靠"打包 → 点界面"来验证 —— 一次 40 秒起步，
    而且分不清"后端没更新"和"前端写错了"（实测踩过一次：内置 exe 还是旧版，
    页面报 404，看起来像前端 bug）。

    这份测试把**契约本身**钉死：字段名、状态码、状态机顺序。
    前端只要照这里的形状实现，就不需要反复起界面验证。

跑法（仓库根）：
    uv sync --all-packages
    .venv\\Scripts\\python.exe -m pytest apps/desktop/tests/test_api_contracts.py -v

覆盖：
    1. /healthz 形状
    2. 会话 CRUD：创建 → 列表 → 重命名 → 删除（删后 404）
    3. 新会话的历史为空
    4. 任务列表契约（thread_title / instruction / status）
    5. 审批列表契约（状态过滤、非法状态 422）
    6. 审批全链路：中断 → pending 可恢复 → decisions 落库 → resume 完成
"""

from __future__ import annotations

import json
import uuid


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def create_thread(client, title: str = "契约测试") -> str:
    response = client.post("/agent/threads", json={"title": title})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def run_chat(client, thread_id: str) -> list[dict]:
    response = client.post(
        "/agent",
        json={"user_input": "写个文件", "chat_thread_id": thread_id},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


# ── 1. 健康检查 ────────────────────────────────────────────────────────────
def test_healthz_shape(app_client):
    body = app_client.get("/healthz").json()
    assert body["status"] == "ok"
    assert {"checkpoint_store", "graph", "timeout_scanner", "llm_key_configured"} <= set(body)


# ── 2. 会话 CRUD ──────────────────────────────────────────────────────────
def test_thread_crud_contract(app_client):
    thread_id = create_thread(app_client, "会话A")

    listed = app_client.get("/agent/threads?page=1&size=20").json()
    assert listed["total"] >= 1
    assert {"id", "title", "updated_at", "user_id", "created_at"} <= set(listed["items"][0])
    assert any(item["id"] == thread_id and item["title"] == "会话A" for item in listed["items"])

    renamed = app_client.patch(f"/agent/threads/{thread_id}", json={"title": "会话B"})
    assert renamed.status_code == 200, renamed.text

    after = app_client.get("/agent/threads?page=1&size=20").json()
    assert any(item["id"] == thread_id and item["title"] == "会话B" for item in after["items"])

    deleted = app_client.delete(f"/agent/threads/{thread_id}")
    assert deleted.status_code == 200, deleted.text

    after_delete = app_client.get("/agent/threads?page=1&size=20").json()
    assert all(item["id"] != thread_id for item in after_delete["items"])


# ── 3. 新会话历史为空 ─────────────────────────────────────────────────────
def test_messages_empty_for_new_thread(app_client):
    thread_id = create_thread(app_client)
    body = app_client.get(f"/agent/threads/{thread_id}/messages").json()
    assert body["total"] == 0
    assert body["items"] == []


# ── 4/5. 列表契约 + 6. 审批全链路 ──────────────────────────────────────────
def test_approval_flow_contract(app_client):
    thread_id = create_thread(app_client, "审批线程")

    events = run_chat(app_client, thread_id)
    types = [event["type"] for event in events]
    assert "approval_required" in types, types
    assert events[-1] == {"type": "done", "status": "interrupted"}

    approval_event = next(e for e in events if e["type"] == "approval_required")
    review = approval_event["review"]
    assert review["type"] == "review_request"
    assert len(review["requests"]) == 1
    request = review["requests"][0]
    assert request["tool_call_id"] == "call_w1"
    assert request["path"] == "out.txt"
    assert request["is_new_file"] is True
    assert "diff" in request
    # 后端回填的 approval_id 是数据库行 id，前端靠它精确审批
    assert request.get("approval_id")

    # ── 任务列表契约 ──
    tasks = app_client.get("/agent/tasks?page=1&size=20").json()
    assert tasks["total"] == 1
    task = tasks["items"][0]
    assert task["thread_id"] == thread_id
    assert task["thread_title"] == "审批线程"
    assert task["instruction"] == "写个文件"
    assert task["status"] == "WAITING_APPROVAL"
    assert {"id", "created_at", "updated_at"} <= set(task)

    # ── 审批列表契约 ──
    approvals = app_client.get("/agent/approvals?page=1&size=20").json()
    assert approvals["total"] == 1
    item = approvals["items"][0]
    assert item["thread_id"] == thread_id
    assert item["thread_title"] == "审批线程"
    assert item["tool_name"] == "write_file_tool"
    assert item["target_path"] == "out.txt"
    assert item["approval_status"] == "PENDING"
    assert item["tool_execution_status"] == "NOT_STARTED"
    assert item["execution_id"]

    only_pending = app_client.get("/agent/approvals?status=PENDING&page=1&size=20").json()
    assert only_pending["total"] == 1
    only_approved = app_client.get("/agent/approvals?status=APPROVED&page=1&size=20").json()
    assert only_approved["total"] == 0

    invalid = app_client.get("/agent/approvals?status=BOGUS")
    assert invalid.status_code == 422, invalid.text

    # ── 刷新恢复：pending 端点必须能拿到同一份 review ──
    pending = app_client.get(f"/agent/threads/{thread_id}/pending").json()
    assert pending["pending"] is not None
    assert pending["pending"]["interrupt_id"] == approval_event["interrupt_id"]
    assert pending["pending"]["review"]["requests"][0]["tool_call_id"] == "call_w1"

    # ── 第一步：落库（不跑图）──
    decisions = app_client.post(
        "/agent/decisions",
        json={
            "chat_thread_id": thread_id,
            "decisions": [
                {
                    "approval_id": request["approval_id"],
                    "tool_call_id": "call_w1",
                    "action": "approve",
                    "reason": None,
                }
            ],
        },
    )
    assert decisions.status_code == 200, decisions.text

    # ── 第二步：恢复并续跑 ──
    resume = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": thread_id,
            "review": {
                "type": "review_decision",
                "decisions": [
                    {"tool_call_id": "call_w1", "action": "approve", "reason": None}
                ],
            },
        },
    )
    assert resume.status_code == 200, resume.text
    resume_events = parse_sse(resume.text)
    assert resume_events[-1] == {"type": "done", "status": "completed"}, resume_events[-1]

    # 工具真的执行了
    assert (app_client.sandbox / "out.txt").read_text(encoding="utf-8") == "approved!"

    # ── 落库结果与状态机 ──
    final = app_client.get("/agent/approvals?page=1&size=20").json()["items"][0]
    assert final["approval_status"] == "APPROVED"
    assert final["tool_execution_status"] == "SUCCEEDED"
    assert final["decided_at"] is not None

    final_task = app_client.get("/agent/tasks?page=1&size=20").json()["items"][0]
    assert final_task["status"] == "COMPLETED"

    # ── 恢复之后 pending 必须清空 ──
    assert app_client.get(f"/agent/threads/{thread_id}/pending").json()["pending"] is None

    # ── 历史：用户消息 + 助手回复（result 回填）──
    history = app_client.get(f"/agent/threads/{thread_id}/messages").json()
    roles = [entry["role"] for entry in history["items"]]
    assert roles[0] == "user"
    assert "assistant" in roles


def test_pending_none_for_fresh_thread(app_client):
    thread_id = create_thread(app_client)
    assert app_client.get(f"/agent/threads/{thread_id}/pending").json()["pending"] is None


# ── 7. resume 的负向契约（原 smoke_http_resume.py 的 2/3/4/6 条）──────────
def test_resume_rejects_bad_requests(app_client):
    thread_id = create_thread(app_client, "负向")
    events = run_chat(app_client, thread_id)
    assert events[-1] == {"type": "done", "status": "interrupted"}

    # 决定与挂起项不匹配 → 409，且绝不执行
    mismatch = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": thread_id,
            "review": {
                "type": "review_decision",
                "decisions": [
                    {"tool_call_id": "forged", "action": "approve", "reason": None}
                ],
            },
        },
    )
    assert mismatch.status_code == 409, mismatch.text
    assert not (app_client.sandbox / "out.txt").exists()

    # 未知线程 → 404
    unknown = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": str(uuid.uuid4()),
            "review": {
                "decisions": [{"tool_call_id": "call_w1", "action": "approve"}]
            },
        },
    )
    assert unknown.status_code == 404, unknown.text

    # 未挂起的线程 → 409
    other_thread = create_thread(app_client, "未挂起")
    not_suspended = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": other_thread,
            "review": {
                "decisions": [{"tool_call_id": "call_w1", "action": "approve"}]
            },
        },
    )
    assert not_suspended.status_code == 409, not_suspended.text

    # 正确决定 → 200 且完成
    ok = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": thread_id,
            "review": {
                "type": "review_decision",
                "decisions": [
                    {"tool_call_id": "call_w1", "action": "approve", "reason": None}
                ],
            },
        },
    )
    assert ok.status_code == 200, ok.text
    assert parse_sse(ok.text)[-1] == {"type": "done", "status": "completed"}
    assert (app_client.sandbox / "out.txt").read_text(encoding="utf-8") == "approved!"

    # 重放同一审批 → 409
    replay = app_client.post(
        "/agent/resume",
        json={
            "chat_thread_id": thread_id,
            "review": {
                "decisions": [{"tool_call_id": "call_w1", "action": "approve"}]
            },
        },
    )
    assert replay.status_code == 409, replay.text
