# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
"""详情接口契约测试（任务 / 执行 / 审批）。

为什么要单独一份：
    前端删掉 demo 数据后，任务详情、执行详情、审批记录三个页面全部依赖
    这三个新接口。如果只靠点界面验证，字段一改（比如 `finished_at` 改名）
    前端会静默拿到 undefined —— 页面不报错，只是空白。

    这里把**字段集**和**404 语义**钉死。

跑法（仓库根）：
    .venv\\Scripts\\python.exe -m pytest apps/desktop/tests/test_detail_api.py -v

覆盖：
    1. GET /agent/tasks/{id}      —— 形状 + executions + approvals
    2. GET /agent/executions/{id} —— 形状 + task 摘要
    3. GET /agent/approvals/{id}  —— 形状 + task 摘要
    4. 未知 id 一律 404（不区分"不存在"与"不是你的"）
    5. GET /agent/tasks?thread_id= 只返回该会话的任务
"""

from __future__ import annotations

import uuid

from test_api_contracts import create_thread, run_chat

TASK_FIELDS = {
    "id",
    "thread_id",
    "thread_title",
    "instruction",
    "status",
    "failure_reason",
    "created_at",
    "updated_at",
}

EXECUTION_FIELDS = {
    "id",
    "task_id",
    "status",
    "graph_thread_id",
    "validation_failure_reason",
    "created_at",
    "finished_at",
}

APPROVAL_FIELDS = {
    "id",
    "task_id",
    "execution_id",
    "thread_id",
    "thread_title",
    "tool_name",
    "target_path",
    "approval_status",
    "tool_execution_status",
    "created_at",
    "decided_at",
    "decision_reason",
}


def _prepare_run(client):
    """跑一轮会产生任务 + 执行 + 审批中断的对话，返回 thread_id。"""
    thread_id = create_thread(client, "详情契约")
    run_chat(client, thread_id)
    return thread_id


# ── 1. 任务详情 ────────────────────────────────────────────────────────────
def test_task_detail_contract(app_client):
    thread_id = _prepare_run(app_client)

    listed = app_client.get("/agent/tasks?page=1&size=20").json()
    assert listed["total"] >= 1
    task_id = listed["items"][0]["id"]

    response = app_client.get(f"/agent/tasks/{task_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert TASK_FIELDS <= set(body)
    assert body["id"] == task_id
    assert body["thread_id"] == thread_id
    # 详情返回**完整** instruction，列表才截断 200 字
    assert isinstance(body["instruction"], str) and body["instruction"]

    assert isinstance(body["executions"], list)
    assert len(body["executions"]) >= 1
    assert EXECUTION_FIELDS <= set(body["executions"][0])

    assert isinstance(body["approvals"], list)
    for item in body["approvals"]:
        assert APPROVAL_FIELDS <= set(item)


# ── 2. 执行详情 ────────────────────────────────────────────────────────────
def test_execution_detail_contract(app_client):
    _prepare_run(app_client)

    task = app_client.get("/agent/tasks?page=1&size=20").json()["items"][0]
    detail = app_client.get(f"/agent/tasks/{task['id']}").json()
    execution_id = detail["executions"][0]["id"]

    response = app_client.get(f"/agent/executions/{execution_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert EXECUTION_FIELDS <= set(body)
    assert body["id"] == execution_id
    assert body["task_id"] == task["id"]
    assert body["thread_id"] == task["thread_id"]
    assert TASK_FIELDS <= set(body["task"])
    assert isinstance(body["approvals"], list)


# ── 3. 审批详情 ────────────────────────────────────────────────────────────
def test_approval_detail_contract(app_client):
    _prepare_run(app_client)

    approvals = app_client.get("/agent/approvals?page=1&size=20").json()
    assert approvals["total"] >= 1, "审计链路应产生至少一条审批"
    approval_id = approvals["items"][0]["id"]

    response = app_client.get(f"/agent/approvals/{approval_id}")
    assert response.status_code == 200, response.text
    body = response.json()

    assert APPROVAL_FIELDS <= set(body)
    assert body["id"] == approval_id
    assert TASK_FIELDS <= set(body["task"])
    assert body["task"]["id"] == body["task_id"]


# ── 4. 未知 id → 404 ──────────────────────────────────────────────────────
def test_unknown_ids_return_404(app_client):
    missing = uuid.uuid4()
    assert app_client.get(f"/agent/tasks/{missing}").status_code == 404
    assert app_client.get(f"/agent/executions/{missing}").status_code == 404
    assert app_client.get(f"/agent/approvals/{missing}").status_code == 404


# ── 5. 按会话过滤任务 ─────────────────────────────────────────────────────
def test_tasks_filtered_by_thread(app_client):
    _prepare_run(app_client)
    other_thread = _prepare_run(app_client)

    filtered = app_client.get(f"/agent/tasks?thread_id={other_thread}").json()
    assert filtered["total"] >= 1
    assert all(item["thread_id"] == other_thread for item in filtered["items"])

    missing = uuid.uuid4()
    empty = app_client.get(f"/agent/tasks?thread_id={missing}").json()
    assert empty["total"] == 0 and empty["items"] == []
