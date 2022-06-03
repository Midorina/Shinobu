from __future__ import annotations

import functools
import logging
from abc import ABC, abstractmethod
from typing import Dict

import aioredis
from aioredis import ConnectionPool, Redis

REDIS_NOT_WORKING = False


class BaseCache(ABC):
    def __init__(self, bot):
        self.bot = bot

    @abstractmethod
    async def get_keys(self):
        pass

    @abstractmethod
    async def get(self, key: str):
        pass

    @abstractmethod
    async def get_key_length(self, key: str):
        pass

    @abstractmethod
    async def pop_random(self, key: str):
        pass

    @abstractmethod
    async def append(self, key: str, *values: str):
        pass

    async def disconnect(self):
        pass


class LocalCache(BaseCache):
    def __init__(self, bot):
        super(LocalCache, self).__init__(bot)

        self.cache: Dict[str, set] = dict()

    async def get_keys(self):
        return self.cache.keys()

    async def get(self, key: str):
        return self.cache[key]

    async def get_key_length(self, key: str):
        return len(self.cache[key])

    async def pop_random(self, key: str) -> str:
        return self.cache[key].pop()

    async def append(self, key: str, *values: str) -> None:
        try:
            self.cache[key].add(values)
        except (KeyError, IndexError):
            self.cache[key] = set(values)

        # TODO implement expiration for local cache


def redis_falls_back_to_local(func):
    @functools.wraps(func)
    async def wrapper(self, *args, **kwargs):
        global REDIS_NOT_WORKING

        try:
            # if REDIS_NOT_WORKING:
            #     raise aioredis.ConnectionError

            return await func(self, *args, **kwargs)

        except aioredis.ConnectionError:
            if not REDIS_NOT_WORKING:
                REDIS_NOT_WORKING = True

                logging.warning(
                    "Redis connection has failed. Falling back to local cache. Redis is strongly suggested.")

            return await getattr(super(self.__class__, self), func.__name__)(*args, **kwargs)

    return wrapper


class RedisCache(LocalCache):
    def __init__(self, bot):
        super(RedisCache, self).__init__(bot)

        self._pool: ConnectionPool = aioredis.ConnectionPool.from_url(
            self.bot.config.redis_host,
            max_connections=20,
            decode_responses=True)
        self.redis_cache: Redis = aioredis.Redis(connection_pool=self._pool)

    @redis_falls_back_to_local
    async def get_keys(self):
        return await self.redis_cache.keys()

    @redis_falls_back_to_local
    async def get(self, key: str):
        return await self.redis_cache.get(key)

    @redis_falls_back_to_local
    async def get_key_length(self, key: str) -> int:
        return await self.redis_cache.scard(key)

    @redis_falls_back_to_local
    async def pop_random(self, key: str) -> str:
        # for some unknown reason, sometimes spop returns all values???
        # so specify a count to make sure to receive a tuple
        # and only return the first one
        return (await self.redis_cache.spop(key, 1))[0]

    @redis_falls_back_to_local
    async def append(self, key: str, *values: str) -> None:
        await self.redis_cache.sadd(key, *values)
        await self.redis_cache.expire(key, 3600)  # expire after one hour

    @redis_falls_back_to_local
    async def disconnect(self) -> None:
        await self.redis_cache.close()
