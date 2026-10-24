"""桌面端审批超时扫描的启停与配置归一化。

# ── AI-ASSISTED ── 本文件由 AI 生成/改写，待人工复核 ──
# 复核重点：
#   1. 循环**先 sleep 再扫**：首轮延迟一个间隔（ADR 已确认）。
#   2. 非取消异常必须被吞掉并记录，否则后台任务会静默退出。
#   3. interval=0 是合法的“关闭”；负数 clamp 到 0 且打 ERROR（不静默）。
#   4. 本模块只负责“跑扫描”，不解释业务结果。
"""

from __future__ import annotations

import asyncio
import logging

from furina_core.task.timeout_scanner import scan_once

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 50


def normalize_scan_settings(*, interval: int, batch: int) -> tuple[int, int]:
    """非法配置降级为可用值，并留下 ERROR 日志。"""
    if interval < 0:
        logger.error(
            "APPROVAL_SCAN_INTERVAL_SECONDS=%s 非法（<0），按 0（关闭扫描）处理", interval
        )
        interval = 0
    if batch <= 0:
        logger.error(
            "APPROVAL_SCAN_BATCH_SIZE=%s 非法（<=0），回退默认 %d", batch, DEFAULT_BATCH_SIZE
        )
        batch = DEFAULT_BATCH_SIZE
    return interval, batch


async def _loop(session_factory, *, interval: int, batch: int) -> None:
    while True:
        await asyncio.sleep(interval)  # 首轮延迟一个间隔
        try:
            report = await scan_once(session_factory, limit=batch)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 循环必须活下来
            logger.exception("审批超时扫描失败，将在下一轮重试")
            continue

        if report.has_activity:
            logger.info("审批超时扫描：%s", report)
        else:
            logger.debug("审批超时扫描：无动作 %s", report)


def start_timeout_scanner(
    app,
    *,
    session_factory,
    interval: int,
    batch: int,
) -> str:
    """启动后台扫描，返回最终状态（running / disabled）。幂等：重复调用先停旧的。"""
    interval, batch = normalize_scan_settings(interval=interval, batch=batch)
    logger.info(
        "审批超时扫描配置：interval=%ss batch=%s", interval, batch
    )

    if interval == 0:
        app.state.timeout_scanner_task = None
        app.state.timeout_scanner_status = "disabled"
        return "disabled"

    task = asyncio.create_task(
        _loop(session_factory, interval=interval, batch=batch),
        name="approval-timeout-scanner",
    )
    app.state.timeout_scanner_task = task
    app.state.timeout_scanner_status = "running"
    return "running"


async def stop_timeout_scanner(app) -> None:
    """取消并等待后台任务；异常只记录，不阻塞关闭流程。"""
    task = getattr(app.state, "timeout_scanner_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("审批超时扫描任务退出时异常")
    app.state.timeout_scanner_task = None
    app.state.timeout_scanner_status = "stopped"
