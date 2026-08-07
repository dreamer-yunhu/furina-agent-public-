"""
redis缓存读写，以及JWT黑名单
"""
from redis import asyncio as aioredis


#定义将热消息先存入redis消息列队中
async def save_user_hot_message(message : str,redis:aioredis.Redis):
    pass


#定义将大模型热回复存入redis
async def save_llm_hot_message():
    pass




#定义JWT黑名单函数
async def jwt_block_list(redis:aioredis.Redis,token_jti:str,ttl:int):
    #将token剩余过期时间存入redis
    await redis.set(name = f"jti:blocklist:{token_jti}",value = "已过期" ,ex = ttl)

#定义查看是否把预定id成功加入黑名单的函数
async def is_blocklisted(redis:aioredis.Redis,jti:str)->bool:
    #检查函数不用关心其他逻辑
    blocklisted_id =  await redis.exists(f"jti:blocklist:{jti}")
    return bool(blocklisted_id)

#定义登记会话id的函数
async def register_session(redis:aioredis.Redis,user_id:str,session_id:str):
    await redis.set(name=f"user:session:{user_id}",value = session_id)

#定义校验函数
async def is_current_session(redis:aioredis.Redis,session_id:str,user_id:str)->bool:
    current_session = await redis.get(f"user:session:{user_id}")
    return current_session == session_id

#定义登出撤销会话函数
async def clear_session(redis:aioredis.Redis,user_id:str):
    await redis.delete(f"user:session:{user_id}")