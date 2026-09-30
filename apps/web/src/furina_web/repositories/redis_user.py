"""
redis缓存读写，以及JWT黑名单
"""
import json
from redis import asyncio as aioredis



#定义将热消息先存入redis消息列队中
async def save_hot_message(redis:aioredis.Redis,conv_id:str,role:str,content:str):
    key = f"chat:conversation:{conv_id}"
    msg = json.dumps({"role":role,"content":content})
    pipe = redis.pipeline() #管道工，redis精髓，可以一次执行多条操作
    pipe.rpush(key,msg)
    pipe.ltrim(key,-30,-1) #只选最新30条，其余裁剪删除——（redis的list切片是闭区间）
    pipe.expire(key,3600*12)
    await pipe.execute()


#定义查询热消息的函数
async def get_hot_message(redis:aioredis.Redis,conv_id:str,limit:int=30):
    msgs =  await redis.lrange(
        name = f"chat:conversation:{conv_id}",
        start= -limit,
        end = -1
    )
    return [json.loads(m) for m in msgs] # 反序列化回列表
    #load()接收文件作为参数，loads()接收字符串作为参数


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
    await redis.set(name=f"user:session:{user_id}",value = session_id,ex = 24*3600*30)

#定义校验函数
async def is_current_session(redis:aioredis.Redis,session_id:str,user_id:str)->bool:
    current_session = await redis.get(f"user:session:{user_id}")
    return current_session == session_id

#定义登出撤销会话函数
async def clear_session(redis:aioredis.Redis,user_id:str):
    await redis.delete(f"user:session:{user_id}")