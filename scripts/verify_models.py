# -*- coding: utf-8 -*-
r"""ORM 冒烟：四张表到底能不能被查询（= mapper 能不能配置成功）。

# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
# 复核重点：
#   1. 这个脚本存在的唯一理由：**import 成功不等于 ORM 能用**。
#      `User.conversations` / `Conversation.messages` 这类跨模块、前向引用的关系，
#      在 import 阶段完全正常，只在 configure_mappers（第一次真实查询）时才炸。
#      本项目已经栽过两次（详见 packages/core/src/furina_core/models.py 文件头）。
#   2. 两个模式**必须分进程跑**：desktop 要验的是"注册表里没有 Conversation 也能配置"，
#      同进程先跑 web 就破坏了这个前提。所以这里不接受 `all`。
#   3. 断言很弱（只验"能查、返回 0 行"）—— 它防的是 mapper 配置错误，不是业务正确性。

用法（在仓库根）：

    $env:PYTHONPATH = "packages\core\src;apps\web\src;apps\desktop\src"
    .venv-build\\Scripts\\python.exe scripts\\verify_models.py web
    .venv-build\\Scripts\\python.exe scripts\\verify_models.py desktop
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if len(sys.argv) < 2 or sys.argv[1] not in ("web", "desktop"):
    print("用法: python scripts/verify_models.py web|desktop")
    raise SystemExit(2)
mode = sys.argv[1]

from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from furina_core.models import AgentThreadID, User  # noqa: E402

if mode == "web":
    from furina_web.models.table import Conversation, Message

    checks = [User, AgentThreadID, Conversation, Message]
else:
    checks = [User, AgentThreadID]

engine = create_engine("sqlite://")
SQLModel.metadata.create_all(engine)
print(f"[{mode}] create_all -> 表: {sorted(SQLModel.metadata.tables)}")

ok = True
for model in checks:
    try:
        with Session(engine) as s:
            rows = s.exec(select(model)).all()
        print(f"  [{mode}] select({model.__name__:<14}) -> OK rows={len(rows)}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [{mode}] select({model.__name__:<14}) -> {type(e).__name__}: {str(e)[:140]}")

if mode == "web":
    from sqlalchemy.orm import configure_mappers

    try:
        configure_mappers()
        rel = Conversation.__mapper__.relationships["user"]
        print(f"  [web] Conversation.user -> {rel.target.name} ({rel.direction.name})")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [web] configure_mappers -> {type(e).__name__}: {str(e)[:160]}")

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
