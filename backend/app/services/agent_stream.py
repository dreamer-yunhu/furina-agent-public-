"""
作为fastapi和Langgraph的桥接层——把输出结果流式呈递给用户
"""
import json
from langgraph.graph import StateGraph
from app.schemas.model import AgentRequest


async def agent_stream(*,
        inform:AgentRequest,
        graph:StateGraph,
):
    messages ={
        "messages":[{"role":"user","content":inform.user_input}]
    }
    async for event in graph.astream(
        messages,
        config ={"configurable":{"thread_id":inform.chat_thread_id}},
        stream_mode = "messages",
        version="v2",
    ):
        if event["type"] == "messages":
            chunk,metadata = event["data"]
            if content:= chunk.content:
                yield f"data: {json.dumps({'reply':content,'status':'generating'})}\n\n"
            else:
                yield f"data: {json.dumps({'status': 'thinking'})}\n\n"
    yield f"data: {json.dumps({'status': 'done'})}\n\n"