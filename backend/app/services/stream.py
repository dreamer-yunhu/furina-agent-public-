"""
用于启动流式响应,顺手写入数据库
"""
import json
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from redis import asyncio as aioredis

from app.core.config import deepseek_client
from app.core.redis_fuse import RedisFuse
from app.core.fuse_helpers import fuse_fail_open
from app.models.table import Conversation
from app.repositories.message import list_recent_messages, save_message
from app.repositories.redis_user import get_hot_message, save_hot_message
from app.schemas.model import ChatRequest, MessageRole
from app.prompts.furina import SYSTEM_PROMPT
from openai import (
    AuthenticationError, RateLimitError, BadRequestError,
    APIConnectionError, APITimeoutError, InternalServerError, APIError
)


logger = logging.getLogger(__name__) #为该模块配置日志

#定义多轮对话函数
async def stream_chat(*,request:ChatRequest,
                      session:AsyncSession,
                      redis:aioredis.Redis,
                      fuse:RedisFuse,
                      conv:Conversation
                      ):
    #获取历史会话记录
    #走熔断器读 Redis 热缓存；Redis 挂了/熔断 → 降级走 PG
    history = await fuse_fail_open(fuse,get_hot_message,[],redis,str(conv.id),action="从redis中读取历史记录")
    #会话开始时从PG取最新30条消息存入redis
    if not history:
        pg_msg = await list_recent_messages(
            session=session,
            conversation_id=conv.id
        )
        #回填 Redis（走熔断器；Redis 挂了只记日志，不阻塞主流程）
        for m in pg_msg:
            #action 必须是关键字参数，写在位置区会被 *args 吞掉并多传一个位置参数
            if not await fuse_fail_open(fuse, save_hot_message, None,
                                        redis, str(conv.id), m.role, m.content,
                                        action="将PG中数据回填redis"):
                logger.warning("Redis 不可用，PG 回填 Redis 已跳过")
                break
        #拼接历史消息
        history= [{"role":m.role,"content":m.content} for m in pg_msg]
    #存储用户消息
    #先存redis（走熔断器；Redis 挂了只记日志，PG 才是主存储）

    await fuse_fail_open(
        fuse,save_hot_message,None,
        redis,str(conv.id),MessageRole.USER.value,request.user_input,action="将用户消息存入redis"
    )
    #在存入PG
    await save_message(
        session,
        conversation_id=conv.id,
        role = MessageRole.USER,
        content = request.user_input
    )

    #拼接prompt
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        messages.append({"role":msg.get("role"),"content":msg.get("content")})
    user_message = {"role":"user","content":request.user_input}
    messages.append(user_message )

    #利用client客户端发送http请求给模型并开启流式响应
    #sdk返还一个可迭代的封装对象
    logger.info("启动流式响应")
    full_text = ""
    try:
        stream = await deepseek_client.chat.completions.create(
            model = request.model,
            messages = messages,
            max_tokens = request.max_tokens,
            stream = True,#核心，提示模型开启流式响应
        )
        logger.debug("已使用openai库的SDK向大模型发送请求")
        #异步迭代
        logger.debug("使用异步迭代遍历大模型通过http发送回的数据包")
        async for chunk in stream:
            #利用海象运算符解决判断是否为空并向前端发送有效消息
            if content := chunk.choices[0].delta.content:
                full_text += content
                #向前端返还符合SSE协议的消息
                yield f"data: {json.dumps({'reply':content,'status':'generating'})}\n\n"

        #相应完成立刻先存储进入redis再存PG
        if full_text:
            #先存redis（走熔断器；Redis 挂了只记日志，PG 才是主存储）
            await fuse_fail_open(fuse,save_hot_message,None,
                                 redis, str(conv.id),
                                 MessageRole.ASSISTANT.value, full_text,action="将大模型回复存入redis")
            #再存入PG
            await save_message(
                session,
                conversation_id=conv.id,
                role =MessageRole.ASSISTANT,
                content = full_text
            )
        #向前端传递消息发完的信号
        yield f"data: {json.dumps({'status':'done'})}\n\n"
        logger.info("流式响应正常结束")


    #进行异常捕获，注意，异常捕获的时候，从具体到抽象
    except AuthenticationError:
        logging.exception("API密钥无效！！！")
        #该异常用于捕获API密钥错误（可能是密钥失效，格式不对等等）
        yield f"data: {json.dumps({'error':'API 密钥无效，请检查服务器配置', 'code': 'AUTH_ERROR'})}\n\n"

    except RateLimitError:
        logger.warning("请求频率超限")
        #该异常用于捕获请求次数异常
        yield f"data: {json.dumps({'error':'请求太繁忙，请稍后再试','code':'RATE_LIMIT'})}\n\n"

    except BadRequestError as e:
        logger.error("请求格式错误: %s", e)
        #该异常用于捕获请求体中出现的异常
        error_msg = f'请求错误{e}'
        yield f"data: {json.dumps({'error':error_msg,'code':'BAD_REQUEST'})}\n\n"

    except APITimeoutError:
        logger.error("模型响应超时")
        #该异常用于捕获请求超时异常
        yield f"data: {json.dumps({'error':' 模型响应超时，请简化问题或稍后重试','code':'TIMEOUT'})}\n\n"

    except APIConnectionError:
        logger.error("无法连接模型服务")
        #该异常用于无法有效链接大模型api的异常
        yield f"data: {json.dumps({'error':'无法连接到模型服务，请稍后重试','code':'CONNECTION_ERROR'})}\n\n"

    except InternalServerError:
        logger.error("模型服务内部错误")
        #捕获服务器内发送的一些异常
        yield f"data: {json.dumps({'error':'模型服务内部错误','code':'SERVER_ERROR'})}\n\n"

    except APIError as e:
        logger.error("API通用错误: %s", e)
        #之前所有异常的父类，用于捕获其他未列出的 API 错误
        yield f"data: {json.dumps({'error':f'调用失败{e}','code':'API_ERROR'})}\n\n"

    except Exception as e:
        logger.exception("未预料的异常")
        #大类异常兜底
        yield f"data: {json.dumps({'error':f'未知错误{e}','code':'UNKNOWN'})}\n\n"