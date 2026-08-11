"""
用于实现redis熔断器，防止redis宕机导致程序崩溃
"""
import logging
import time
from redis import asyncio as aioredis

logger = logging.getLogger(__name__)

class CircuitOpenError(Exception):
    """熔断短路异常：OPEN 期间禁止访问 Redis"""

class RedisFuse:
    """
    三态熔断器:1-CLOSE 2-OPEN 3-HALF-OPEN
    redis正常时CLOSE，当失败请求达到阈值熔断（OPEN），熔断一段事件后进行小规模尝试（HALF-OPEN），过关即放行，否则继续熔断
    状态迁移全部由内部计数 + 时间戳推导，调用方只感知 call()
    """
    _CLOSE = "CLOSE"
    _OPEN = "OPEN"
    _HALF_OPEN = "HALF_OPEN"
    def __init__(
            self,
            redis:aioredis.Redis,
            fail_threshold:int = 5, #CLOSE下连续失败多少次跳闸
            cooldown_seconds:float|int = 10.0,#OPEN状态下熔断几秒
            probe_success : int = 3,# HALF_OPEN 需连续成功几次进入CLOSED
            probe_failure : int = 3 #HALF_OPEN累计失败几次进入OPEN
                ):
        self._redis = redis
        self._fail_threshold = fail_threshold
        self._cooldown_seconds = cooldown_seconds
        self._probe_success = probe_success
        self._probe_failure= probe_failure # HALF_OPEN状态下累计失败多少次再次进入熔断
        self._state = "CLOSE" #默认状态
        self._fail_count = 0 #CLOSE状态下累计失败次数统计
        self._probe_ok_count = 0 #HALF_OPEN状态下累计成功次数
        self._probe_fail_count = 0 #HALF_OPEN状态下累计失败次数
        self._open_at = 0.0#进入OPEN状态的时间戳

    #
    def _on_failure(self):
        """
        状态函数，用于计数连接失败次数和重连次数
        :return:无
        """
        if self._state == self._CLOSE:
            self._fail_count += 1
            #判断是否达到熔断阈值
            if self._fail_count >=self._fail_threshold:
                #熔断
                self._state = self._OPEN
                self._open_at = time.monotonic()
                #记入日志（先打印再归零，否则日志永远显示 0 次）
                logger.warning("连续失败 %d 次，熔断 OPEN", self._fail_count)
                #计数器归零操作
                self._fail_count = 0
        elif self._state == self._HALF_OPEN:
            self._probe_fail_count +=1
            if self._probe_fail_count >= self._probe_failure:
                self._state = self._OPEN
                self._open_at = time.monotonic()
                #计数器归零操作
                self._probe_ok_count = 0
                self._probe_fail_count = 0
                logger.warning("HALF_OPEN 探测失败，回 OPEN")

    def _on_success(self):
        """
        状态函数，用于统计连接成功和重连次数
        :return:无
        """
        if self._state == self._CLOSE:
            self._fail_count = 0 #成功即清零连续失败
        elif self._state == self._HALF_OPEN:
            self._probe_ok_count +=1
            if self._probe_ok_count >= self._probe_success:
                self._state = self._CLOSE
                #记入日志（先打印再归零，否则日志永远显示 0 次）
                logger.info("探测成功 %d 次，恢复 CLOSED", self._probe_ok_count)
                #计数器归零操作
                self._fail_count = 0#重连成功将失败次数清零
                self._probe_fail_count = 0 #重连成功一次将重连累计失败次数清零
                self._probe_ok_count = 0#将成功次数清零

    async def __call__(self,fn,*args,**kwargs):
        """
        执行 redis操作并记录成败，驱动状态机。调用方只管它抛不抛错（人话：智能保险丝函数）
        :param fn:涉及redis操作的函数
        :param args:不定长参数
        :param kwargs:不定长参数
        :return:
        """
        #门闸
        #情况2：熔断时间过后尝试重连
        if self._state == self._OPEN:
            if time.monotonic() - self._open_at >= self._cooldown_seconds:
                self._state = self._HALF_OPEN
                #计数器归零操作
                self._probe_ok_count = 0
                self._probe_fail_count = 0
                logger.info("冷却结束，进入 HALF_OPEN 试探期")
            else:
                raise CircuitOpenError("熔断中")
        try:
            result = await fn(*args,**kwargs)
        except Exception:
            #执行出现异常调用_on_failure函数
            self._on_failure()
            raise
        self._on_success()
        return result

