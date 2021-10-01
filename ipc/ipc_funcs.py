from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import List, Optional, Tuple, Type

import discord
import psutil
import websockets
from async_timeout import timeout

from ipc import ipc_errors
from mido_utils import Time
from models.patreon import UserAndPledgerCombined

__all__ = ['IPCClient', 'SerializedObject']
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


# todo: possibly rewrite this
class IPCMessage:
    MANDATORY_ATTRS = ('author', 'type', 'key')

    def __init__(self, author: id, type: str, key: str, data: dict, created_at: str = None, successful: bool = True):
        self._data = data

        # cluster id
        self.author = author

        # 'response' or 'command'
        self.type = type

        # unique key to identify the requester
        self.key = key

        # whether the response is successful or not
        self.successful = successful

        # creation date
        self.created_at: Time = Time(datetime.strptime(created_at, DATE_FORMAT), offset_naive=True) if created_at \
            else Time(datetime.now())

    def __getattr__(self, item):
        if self.type == 'response' and isinstance(self._data['return_value'], dict) and item != 'return_value':
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
        return {'author'    : self.author,
                'type'      : self.type,
                'key'       : self.key,
                'successful': self.successful,
                'created_at': self.created_at.start_date.strftime(DATE_FORMAT),
                'data'      : self._data}

    def dumps(self) -> str:
        return json.dumps(self.to_json())

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return self.dumps()

    @classmethod
    def get_from_raw(cls, response: str) -> IPCMessage:
        response = json.loads(response.encode('utf8'))
        return cls(**response)


class SerializedObject:
    @classmethod
    def from_dict(cls, data: dict) -> Type[SerializedObject]:
        for key, value in data.items():
            setattr(cls, key, value)

        return cls

    @classmethod
    def from_obj(cls, obj) -> Type[SerializedObject]:
        for key, value in obj.__dict__.items():
            setattr(cls, key, value)

        return cls


class _InternalIPCHandler:
    """Handles receiving and sending requests."""

    # noinspection PyTypeChecker
    def __init__(self, server: IPCServer):
        self.server = server
        self.bot = self.server.bot

        self.port = self.bot.config.ipc_port
        self.identity = f'{self.bot.name}#{self.bot.cluster_id}'

        self.ws: websockets.WebSocketClientProtocol = None
        self.ws_task: asyncio.Task = None

        self.responses = asyncio.Queue()  # or LifoQueue() ?
        self.key_queue = []

        self.bot.loop.create_task(self._connect_to_ipc())
        self.attempting_reconnect = False

    @staticmethod
    def get_key() -> str:
        return uuid.uuid4().hex[:7]

    async def _connect_to_ipc(self):
        while True:
            try:
                self.ws = await websockets.connect(f'ws://localhost:{self.port}')
            except (OSError, asyncio.TimeoutError, websockets.InvalidMessage):
                self.bot.logger.error("Websocket connection attempt is refused. "
                                      f"IPC server is most likely dead or never launched at all.\n"
                                      f"Please launch {os.getcwd()}/ipc/ipc.py with port {self.port}."
                                      " Retrying in 5 seconds...")
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                return self.bot.logger.info("Connecting to ipc task has been cancelled.")
            else:
                await self.ws.send(self.identity.encode('utf-8'))
                await self.ws.recv()
                self.bot.logger.info("Websocket connection succeeded.")
                break

        self.assign_ws_task()

    def assign_ws_task(self):
        if not self.ws_task or self.ws_task.done() is True:
            # if self.ws_task:  # make sure its stopped
            #     self.ws_task.cancel()

            self.ws_task = self.bot.loop.create_task(self._websocket_loop())
            self.ws_task.add_done_callback(self._websocket_loop_done)

    async def _websocket_loop(self):
        self.bot.logger.info("Websocket loop has successfully started.")
        while True:
            try:
                data = IPCMessage.get_from_raw(await self.ws.recv())

                if data.type == 'response':
                    # if we're waiting for this, get it, else, ignore
                    if data.key in self.key_queue:
                        await self.responses.put(data)
                        self.bot.logger.debug(f"Websocket received: {data}")
                    continue

                elif data.type == 'command':
                    try:
                        returned_value = await getattr(self.server, data.endpoint)(data)
                    except Exception as e:
                        ret = IPCMessage(author=self.bot.cluster_id,
                                         type='response',
                                         key=data.key,
                                         successful=False,
                                         data={'return_value': str(e)})
                    else:
                        ret = IPCMessage(author=self.bot.cluster_id,
                                         type='response',
                                         key=data.key,
                                         data={'return_value': returned_value})

                    await self._send(ret.dumps())
                    self.bot.logger.debug("Responded with: " + ret.dumps())
                else:
                    raise ipc_errors.UnknownRequestType

            except websockets.ConnectionClosed as exc:
                self.bot.logger.error(f"Websocket connection seems to be closed with code {exc.code}.")
                await self._try_to_reconnect(sleep=3.0)

            except asyncio.CancelledError as e:
                raise e

            except RuntimeError:
                self.bot.logger.exception("RuntimeError while trying to receive from websocket. "
                                          "Probably duplicate task? Aborting.")
                return

            except Exception:
                self.bot.logger.exception("Unexpected error in websocket loop!")

            await asyncio.sleep(0.01)  # small sleep to not hog

    async def _get_responses(self, key: str) -> List[IPCMessage]:
        ret = []

        try:
            async with timeout(2.0):
                while len(ret) < self.bot.cluster_count:
                    item: IPCMessage = await self.responses.get()

                    if item.key == str(key):
                        # if there was an error, raise it
                        if item.successful is False:
                            raise ipc_errors.RequestFailed(item.return_value)

                        ret.append(item)
                    else:
                        # if it was sent less than 10 seconds ago, put it back
                        # as something else might be waiting to get it
                        if item.created_at.passed_seconds < 10.0:
                            await self.responses.put(item)
                        await asyncio.sleep(0.001)

        except asyncio.TimeoutError:
            pass

        finally:
            self.key_queue.remove(key)

        # sort responses
        ret.sort(key=lambda x: x.author)

        return ret

    async def request(self, endpoint: str, **kwargs) -> List[IPCMessage]:
        key = self.get_key()

        # put the key in the queue so that the response doesn't get ignored
        self.key_queue.append(key)

        msg = IPCMessage(author=self.bot.cluster_id,
                         type='command',
                         data={'endpoint': endpoint,
                               **kwargs},
                         key=key)

        await self._send(msg.dumps())
        self.bot.logger.debug("Made request to the websocket: " + msg.dumps())

        return await self._get_responses(msg.key)

    async def _try_to_reconnect(self, sleep=1.0):
        if self.attempting_reconnect is False:
            self.attempting_reconnect = True
            self.bot.logger.info("Attempting reconnect...")
            try:
                await self._connect_to_ipc()
            except Exception:
                self.bot.logger.exception(f"Exception occurred while trying to reconnect!")
            else:
                self.bot.logger.info("Successfully reconnected!")
            finally:
                self.attempting_reconnect = False
        else:
            self.bot.logger.info("Looks like we're already attempting reconnect. Sleeping...")

        await asyncio.sleep(sleep)

    async def _send(self, data: str):
        attempt = 0
        while attempt < 5:
            attempt += 1
            try:
                await self.ws.send(data)
            except (websockets.ConnectionClosed, AttributeError):
                self.bot.logger.error(f"Websocket connection seems to be closed. "
                                      f"Waiting for connection to be recovered to send the message: {data}")
                await self._try_to_reconnect(sleep=1.0)
            else:
                return

    async def close(self, reason: str = 'Close called.'):
        self.ws_task.cancel()
        self.ws_task = None

        await self.ws.close(code=1000, reason=reason)

    def _websocket_loop_done(self, task):
        try:
            if task.exception():  # if there was an exception besides CancelledError, just restart
                task.print_stack()

            self.assign_ws_task()

        except asyncio.CancelledError:
            self.bot.logger.info("Websocket loop task cancelled.")


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
        await self.bot.wait_until_ready()

        if self.bot.log_channel:
            embed = discord.Embed.from_dict(data.embed) if data.embed else None
            content = data.content[:2000] if data.content else None

            await self.bot.log_channel.send(content=content, embed=embed)
            return True

    async def get_guild_count(self, data: IPCMessage):
        return len(self.bot.guilds)

    async def user_has_voted(self, data: IPCMessage):
        cog = self.bot.get_cog('Gambling')
        return await cog.user_has_voted(data.user_id)

    async def get_user(self, data: IPCMessage):
        user: Optional[discord.User] = self.bot.get_user(data.user_id)
        if user:
            return {
                'name'         : user.name,
                'id'           : user.id,
                'avatar_url'   : str(user.avatar_url),
                'discriminator': user.discriminator,
                'bot'          : user.bot,
                'display_name' : user.display_name
            }

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
            "music_players": len(self.bot.wavelink.players) if hasattr(self.bot, 'wavelink') else 0
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
        responses = await self.handler.request('send_to_log_channel', content=content,
                                               embed=embed.to_dict() if embed else None)
        if not any(x.return_value for x in responses):
            self.bot.logger.error(
                f"Message could not be sent to the log channel. "
                f"Please make sure you pass an ID of a proper channel that bot can post in to the config file.\n"
                f"Content: {content}\n"
                f"Embed: {embed.to_dict() if embed else None}")

    async def get_guild_count(self) -> int:
        responses = await self.handler.request('get_guild_count')
        return sum(x.return_value for x in responses)

    async def user_has_voted(self, user_id: int) -> bool:
        responses = await self.handler.request('user_has_voted', user_id=user_id)
        return any(x.return_value for x in responses)

    async def get_user(self, user_id: int) -> Optional[Type[SerializedObject]]:
        responses = await self.handler.request('get_user', user_id=user_id)
        for response in responses:
            if response.return_value:
                return SerializedObject.from_dict(response.return_value)

    async def reload(self, target_cog: str = None) -> List[Tuple[int, int]]:
        """Returns (Cluster ID, Reloaded Cog Count]"""
        responses = await self.handler.request('reload', target_cog=target_cog)

        return [(x.author, x.return_value) for x in responses]

    async def shutdown(self, cluster_id: int = None) -> None:
        await self.handler.request('shutdown', cluster_id=cluster_id)

    async def close_ipc(self, reason: str = 'Close called by bot.') -> None:
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
