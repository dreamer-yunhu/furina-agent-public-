"""
用于定义redis限流器，防止高并发请求压垮后端
"""
import time
from redis import asyncio as aioredis

#定义redis限流异常——方便达到限流阈值后直接中断程序
class RedisLimitException(Exception):
    """
    触发直接429
    """
    pass

#定义限流器本体
class TokenBucketLimiter:
    """
    令牌桶限流器(单桶单键,LUA 保证原子)
    每个 key 对应一个桶:capacity 容量,rate 每秒补充令牌数
    调用方只感知 acquire() 返回 bool / 抛不抛异常
    """
    def __init__(self, redis: aioredis.Redis,
                 capacity : int = 10,  #桶容量(允许瞬时突发多少)
                 rate : float = 1.0,#每秒补充速率
                 key_prefix: str = "rl:"
                 ):
        self._redis = redis
        self._capacity = capacity
        self._rate = rate
        self._key_prefix = key_prefix