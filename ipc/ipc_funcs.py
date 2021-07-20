from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import List, Optional, Tuple

import discord
import psutil
import websockets
from async_timeout import timeout

from ipc import ipc_errors
from models.patreon import UserAndPledgerCombined

__all__ = ['IPCClient', 'SerializedObject']


class IPCMessage:
    MANDATORY_ATTRS = ('author', 'type', 'key')

    def __init__(self, author: id, type: str, key: str, data: dict):
        self._data = data

        # cluster id
        self.author = author
        # 'response' or 'command'
        self.type = type
        # unique key to identify the requester
        self.key = key

    def __getattr__(self, item):
        if self.type == 'response' and isinstance(self._data['return_value'], dict):
            data_to_look_for = self._data['return_value']
        else:
            data_to_look_for = self._data

        if item in data_to_look_for.keys():
            return data_to_look_for[item]

        return super().__getattribute__(item)

    # def __setattr__(self, key, value):
    #     if key in self.MANDATORY_ATTRS:
    #         return super().__setattr__(key, value)
    #
    #     self._data[key] = value

    def to_json(self) -> dict:
        return {'author': self.author,
                'type'  : self.type,
                'key'   : self.key,
                'data'  : self._data}

    def dumps(self) -> str:
        return json.dumps(self.to_json())

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return self.dumps()

    @classmethod
    def get_from_raw(cls, response: str) -> IPCMessage:
        response = json.loads(response, encoding='utf-8')
        return cls(**response)


class SerializedObject:
    def __init__(self, data: dict):
        for key, value in data.items():
            setattr(self, key, value)


class _InternalIPCHandler:
    """Handles receiving and sending requests."""

    # noinspection PyTypeChecker
    def __init__(self, server: IPCServer):
        self.server = server
        self.bot = self.server.bot

        self.port = self.bot.config['ipc_port']
        self.identity = f'{self.bot.name}#{self.bot.cluster_id}'

        self.ws: websockets.WebSocketClientProtocol = None
        self.ws_task: asyncio.Task = None

        self.responses = asyncio.Queue()
        self.key_queue = []
        self.bot.loop.create_task(self._connect_to_ipc())

    async def close(self, reason: str = 'Close called.'):
        self.ws_task.cancel()
        self.ws_task = None

        await self.ws.close(code=1000, reason=reason)

    @staticmethod
    def get_key() -> str:
        return uuid.uuid4().hex[:7]

    async def _connect_to_ipc(self):
        while True:
            try:
                self.ws = await websockets.connect(f'ws://localhost:{self.port}')

                await self.ws.send(self.identity.encode('utf-8'))
                await self.ws.recv()
            except OSError:
                self.bot.logger.error("Websocket connection attempt is refused. "
                                      "IPC server is most likely to be dead or never launched at all. "
                                      "Retrying in 2 seconds...")
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                return
            else:
                self.bot.logger.info("Websocket connection succeeded.")
                break

        if not self.ws_task:
            self.ws_task = self.bot.loop.create_task(self._websocket_loop())

    async def _get_responses(self, key: str) -> List[IPCMessage]:
        ret = []

        try:
            async with timeout(5.0):
                while len(ret) < self.bot.cluster_count:
                    item: IPCMessage = await self.responses.get()
                    if item.key == str(key):
                        ret.append(item)
                    else:
                        # todo: throw the response away if it was sent more than 6 seconds ago
                        await self.responses.put(item)
                        await asyncio.sleep(0.01)
        except asyncio.TimeoutError:
            pass

        self.key_queue.remove(key)

        # sort responses
        ret.sort(key=lambda x: x.author)
        return ret

    async def _websocket_loop(self):
        self.bot.logger.info("Websocket loop has successfully  started.")
        while True:
            try:
                data = IPCMessage.get_from_raw(await self.ws.recv())

                if data.type == 'response':
                    # if we're waiting for this, get it, else, ignore
                    if data.key in self.key_queue:
                        await self.responses.put(data)
                        self.bot.logger.info(f"Websocket received: {data}")
                    continue

                elif data.type == 'command':
                    returned_value = await getattr(self.server, data.endpoint)(data)
                    ret = IPCMessage(author=self.bot.cluster_id,
                                     type='response',
                                     key=data.key,
                                     data={'return_value': returned_value})
                    await self._send(ret.dumps())
                    self.bot.logger.debug("Responded with: " + ret.dumps())
                else:
                    raise ipc_errors.UnknownRequestType
            except websockets.ConnectionClosed as exc:
                if exc.code == 1000:
                    self.bot.logger.warn("Websocket connection seems to be closed safely. Stopping the websocket loop.")
                    return
                self.bot.logger.error(f"Websocket connection seems to be closed with code {exc.code}.")
                await self._try_to_reconnect()
            except asyncio.CancelledError:
                self.bot.logger.info("Websocket loop task cancelled. Returning...")
                return
            except Exception:
                self.bot.logger.exception("Unexpected error in websocket loop!")

    async def request(self, endpoint: str, **kwargs):
        key = self.get_key()
        # put the key in the queue so that the response doesn't get ignored
        self.key_queue.append(key)

        msg = IPCMessage(author=self.bot.cluster_id,
                         type='command',
                         data={'endpoint': endpoint,
                               **kwargs},
                         key=key)

        await self._send(msg.dumps())
        self.bot.logger.info("Made request: " + msg.dumps())

        return await self._get_responses(msg.key)

    async def _try_to_reconnect(self, sleep=2.0):
        self.bot.logger.info("Attempting reconnect...")
        try:
            await self._connect_to_ipc()
        except Exception:
            self.bot.logger.exception(f"Exception occurred while trying to reconnect!")
        else:
            self.bot.logger.info("Successfully reconnected!")
        await asyncio.sleep(sleep)

    async def _send(self, data: str):
        while True:
            try:
                await self.ws.send(data)
            except websockets.ConnectionClosed:
                self.bot.logger.error(f"Websocket connection seems to be closed. Retrying to send the message: {data}")
                await self._connect_to_ipc()
                await asyncio.sleep(1.0)
                continue
            else:
                return


class IPCServer:
    """Gives data from the bot"""

    def __init__(self, bot):
        self.bot = bot

        self.process = psutil.Process(os.getpid())

        self.cpu_usage_cache = 0

        self.bot.loop.create_task(self.update_cpu_usage_cache())

    async def update_cpu_usage_cache(self):
        """Calculates the cpu usage in the last second in a non-blocking way"""
        while True:
            self.process.cpu_percent(interval=0)
            await asyncio.sleep(1.0)
            self.cpu_usage_cache = self.process.cpu_percent(interval=0)

    async def send_to_log_channel(self, data: IPCMessage):
        if self.bot.log_channel:
            embed = discord.Embed.from_dict(data.embed) if data.embed else None
            await self.bot.log_channel.send(content=data.content, embed=embed)
            return True

    async def get_guild_count(self, data: IPCMessage):
        return len(self.bot.guilds)

    async def user_has_voted(self, data: IPCMessage):
        cog = self.bot.get_cog('Gambling')
        return await cog.user_has_voted(data.user_id)

    async def get_user(self, data: IPCMessage):
        return self.bot.get_user(data.user_id)

    async def reload(self, data: IPCMessage):
        target_cog = getattr(data, 'target_cog', None)
        return self.bot.load_or_reload_cogs(target_cog)

    async def shutdown(self, data: IPCMessage):
        if data.cluster_id is None or int(data.cluster_id) == self.bot.cluster_id:
            await self.bot.close()
            return True

        return False

    async def get_cluster_stats(self, data: IPCMessage):
        return {
            "uptime"       : self.bot.uptime.passed_seconds_in_float,
            "cluster_id"   : self.bot.cluster_id,
            "latency"      : self.bot.latency,

            "guilds"       : len(self.bot.guilds),
            "channels"     : len([channel for guild in self.bot.guilds for channel in guild.channels]),
            "members"      : len(list(self.bot.get_all_members())),

            "memory"       : self.process.memory_info().rss / 10 ** 6,
            "threads"      : self.process.num_threads(),
            "cpu_usage"    : self.cpu_usage_cache,
            "music_players": len(self.bot.wavelink.players)
        }

    async def get_patron(self, data: IPCMessage):
        cog = self.bot.get_cog('Gambling')
        if hasattr(cog, 'patreon_api'):
            ret = cog.patreon_api.get_with_discord_id(data.user_id)
            if ret:
                return ret.to_str()

    async def convert_currency(self, data: IPCMessage):
        cog = self.bot.get_cog('Searches')
        if hasattr(cog, 'exchange_api'):
            return await cog.exchange_api.convert(data.amount, data.base_currency, data.target_currency)


class IPCClient:
    """Makes requests and parses args/returned values"""

    def __init__(self, bot):
        self.bot = bot

        self.server = IPCServer(bot=self.bot)
        self.handler = _InternalIPCHandler(self.server)

    async def send_to_log_channel(self, content: str, embed: discord.Embed = None) -> None:
        await self.handler.request('send_to_log_channel', content=content, embed=embed.to_dict() if embed else None)

    async def get_guild_count(self) -> int:
        responses = await self.handler.request('get_guild_count')
        return sum(x.return_value for x in responses)

    async def user_has_voted(self, user_id: int) -> bool:
        responses = await self.handler.request('user_has_voted', user_id=user_id)
        return any(x.return_value for x in responses)

    async def get_user(self, user_id: int) -> Optional[SerializedObject]:
        responses = await self.handler.request('get_user', user_id=user_id)
        for response in responses:
            if response.return_value:
                return SerializedObject(response.return_value)
        return None

    async def reload(self, target_cog: str = None) -> int:
        responses = await self.handler.request('reload', target_cog=target_cog)
        return sum(x.return_value for x in responses)

    async def shutdown(self, cluster_id: int = None) -> None:
        await self.handler.request('shutdown', cluster_id=cluster_id)

    async def close_ipc(self, reason: str = None) -> None:
        await self.handler.close(reason)

    async def get_cluster_stats(self) -> List[IPCMessage]:
        return await self.handler.request('get_cluster_stats')

    async def get_patron(self, user_id: int) -> Optional[UserAndPledgerCombined]:
        responses = await self.handler.request('get_patron', user_id=user_id)
        for response in responses:
            if response.return_value is not None:
                return UserAndPledgerCombined.from_str(response.return_value)

    async def convert_currency(self, amount: float, base_currency: str, target_currency: str) -> Tuple[float, float]:
        """Returns result and exchange rate"""
        responses = await self.handler.request('convert_currency',
                                               amount=amount,
                                               base_currency=base_currency,
                                               target_currency=target_currency)
        for response in responses:
            if response.return_value is not None:
                return response.return_value

# class IPCCommand(IPCMessage):
#     def __init__(self, author: str, key: str, endpoint: str, **command_kwargs):
#         super().__init__(author=author, type='command', key=key, data=dict(**command_kwargs))
#         self.endpoint = endpoint
#
#
# class IPCResponse(IPCMessage):
#     def __init__(self, author: str, key: str, **command_kwargs):
#         super().__init__(author=author, type='response', key=key, data=dict(**command_kwargs))
#         self.data = data


# async def get_user(bot: AutoShardedBot, *args) -> IPCResponse:
#     user: discord.User = bot.get_user(args[0])
#     if not user:
#         return IPCResponse(False, {"reason": "Can't see the user."})
#     else:
#         return IPCResponse(True, data=user.__dict__)
#
#
