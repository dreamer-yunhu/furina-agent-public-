"""
作为fastapi和Langgraph的桥接层——把输出结果流式呈递给用户

⚠️ 2026-09-11 重构：观测通道要能接住中断（PLAN §十四 / 9.8 落地六步 第 1、2 步）

改动要点：
  1. stream_mode 从单字符串 "messages" → 列表 ["messages", "values"]
     - 传列表后，每个 chunk 是 `(mode, payload)` 二元组，必须**先解包再按 mode 分派**
     - 中断挂在 values 流的 payload 上（字段名 interrupts），不在 messages 流里
     - 依据：langgraph `pregel/main.py` 的 v2 路径（chunk 的 interrupts 与 data 平级）
  2. 事件契约升级：status 魔法串 → type 封闭事件集（PLAN §十二 待办）
  3. 竞态兜底：挂起期间新消息到达 → 作废旧 pending（9.8 铁共识 3）

⚠️ 别在 v2 基础上顺手迁 v3 —— stream_events(version="v3") 是 experimental
   （见 PLAN §十四.7 的版本事实表）
"""
import json

from langgraph.graph import StateGraph

from app.schemas.model import AgentRequest


async def agent_stream(*, inform: AgentRequest, graph: StateGraph):
    """把图的流式输出转成 SSE 帧

    TODO: [流-1] 换 stream_mode 并解包
      提示：stream_mode=["messages", "values"]，chunk 是 (mode, payload)
      边界：**先 print 原始帧确认形状再写解析代码**，别照抄这里的注释就开工
            （langgraph 1.2.11 + v2 的实际形状以运行结果为准）
    """
    messages = {"messages": [{"role": "user", "content": inform.user_input}]}
    config = {"configurable": {"thread_id": inform.chat_thread_id}}

    async for event in graph.astream(messages, config=config, stream_mode=["messages", "values"]):
        # TODO: [流-1] 解包 (mode, payload) 并按 mode 分派
        raise NotImplementedError

    # TODO: [流-2] 中断分支
    #   图被中断时 run 会正常结束（不报错），中断信息在 values 流里
    #   这里要 yield 一个 `approval_required` 事件，把下面这些送到前端：
    #     - 审批对象：path + 内容（终极目标是 diff，见 PLAN §十四.2 理由②）
    #     - interrupt.id ← **必须带上**，前端回传时要靠它指明"在回哪个中断"
    #       依据：Command(resume=) 支持 id 键控形态（langgraph/types.py L808-823）
    #     - agent 归属：这个中断来自主管还是 coder（9.8：子代理事件带 agent 归属）
    #   边界：一次中断可能包含 N 个 action，**需要 N 个决定，且顺序必须对应**
    #        （decisions 数量不等 → ValueError）

    # TODO: [流-3] 事件契约封闭集
    #   现在用的 status 魔法串（"generating"/"thinking"/"done"）要升级成 type 封闭集
    #   参考 9.8 的三流派 + PLAN §十二：错误以终态事件送达，而不是断流
    yield f"data: {json.dumps({'status': 'done'})}\n\n"

    # TODO: [流-4] 竞态兜底（9.8 铁共识 3）
    #   审批挂起期间用户又发新消息 → 作废旧 pending
    #   否则残留 pending 会在下次 run 被"隐式放行"静默执行
