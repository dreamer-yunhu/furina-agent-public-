"""
启动redis连接池
"""
import redis.asyncio as aioredis

from app.core.config import settings

redis_client = aioredis.from_url(settings.redis_url,encoding="utf-8",decode_responses=True)


#调试代码，这里用来测试redis受否接通
if __name__ == "__main__":
    if redis_client.ping():
        print("redis连接成功！")

    else:
        print("redis连接失败")