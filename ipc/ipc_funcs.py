from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import List, Optional

import discord
import psutil
import websockets

from ipc import ipc_errors

__all__ = ['IPCClient', 'SerializedObject']


class IPCMessage:
    MANDATORY_ATTRS = ('author', 'type', 'key')

    def __init__(self, author: id, type: str, key: str, data: dict):
        # cluster id
        self.author = author
        # response or command
        self.type = type
        # unique key to identify the requester
        self.key = key

        self._data = data

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
    def __init__(self, server: _IPCServer):
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
        self.ws.close(reason=reason)

    @staticmethod
    def get_key() -> str:
        return uuid.uuid4().hex[:7]

    async def _connect_to_ipc(self):
        self.ws = await websockets.connect(f'ws://localhost:{self.port}')

        await self.ws.send(self.identity.encode('utf-8'))
        await self.ws.recv()

        if not self.ws_task:
            self.ws_task = self.bot.loop.create_task(self._websocket_loop())

        self.bot.logger.info("Websocket connection succeeded.")

    async def _get_responses(self, key: str) -> List[IPCMessage]:
        attempt = 0
        ret = []
        while len(ret) < self.bot.cluster_count and attempt < 200:
            item: IPCMessage = await self.responses.get()
            if item.key == str(key):
                ret.append(item)
            else:
                attempt += 1
                await self.responses.put(item)
                await asyncio.sleep(0.05)

        self.key_queue.remove(key)

        # sort responses
        ret.sort(key=lambda x: x.author)
        return ret

    async def _websocket_loop(self):
        while True:
            try:
                raw_data = await self.ws.recv()
                data = IPCMessage.get_from_raw(raw_data)

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
            except websockets.ConnectionClosed:
                self.bot.logger.error("Websocket connection seems to be closed. Retrying to receive messages...")
                await self._connect_to_ipc()
                await asyncio.sleep(1.0)
                continue
            except Exception as e:
                self.bot.logger.error("error in websocket loop:", str(e))

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


class _IPCServer:
    def __init__(self, bot):
        self.bot = bot

    async def send_to_log_channel(self, data: IPCMessage):
        if self.bot.log_channel:
            await self.bot.log_channel.send(content=data.content, embed=discord.Embed.from_dict(data.embed))
            return True

        # if not bot.log_channel:
        #     return IPCResponse(successful=False, data={'reason': "Can't see the log channel."})
        return False

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
        await self.bot.close()

    async def get_cluster_stats(self, data: IPCMessage):
        process = psutil.Process(os.getpid())

        return {
            "uptime"       : self.bot.uptime.passed_seconds_in_float,
            "cluster_id"   : self.bot.cluster_id,
            "latency"      : self.bot.latency,

            "guilds"       : len(self.bot.guilds),
            "channels"     : len([channel for guild in self.bot.guilds for channel in guild.channels]),
            "members"      : len(list(self.bot.get_all_members())),

            "memory"       : process.memory_info().rss / 10 ** 6,
            "threads"      : process.num_threads(),
            "cpu_usage"    : process.cpu_percent(interval=0),
            "music_players": len(self.bot.wavelink.players)
        }


class IPCClient:
    def __init__(self, bot):
        self.bot = bot

        self.server = _IPCServer(bot=self.bot)
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

    async def shutdown(self):
        await self.handler.request('shutdown')

    async def close_ipc(self, reason: str = None):
        await self.handler.close(reason)

    async def get_cluster_stats(self):
        return await self.handler.request('get_cluster_stats')

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
