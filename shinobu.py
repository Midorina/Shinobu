from __future__ import annotations

import asyncio
import logging
import multiprocessing
import os
import re
from functools import cached_property
from typing import TYPE_CHECKING, Type

import aiohttp
import asyncpg
import discord
import setproctitle
from discord.ext import commands

# anything not imported here will not be reloaded once the cluster is shut down.
# so it's important to import everything but cogs here
import ipc
import mido_utils
import models
from models.db import run_create_table_funcs

if TYPE_CHECKING:
    from cogs.games import Race


class ShinobuBot(commands.AutoShardedBot):
    # noinspection PyTypeChecker
    def __init__(self, **cluster_kwargs):
        self.name = cluster_kwargs.pop('bot_name')
        self.config: models.ConfigFile = self.get_config(self.name, warn=False)

        self.cluster_id: int = cluster_kwargs.pop('cluster_id')
        self.cluster_count = cluster_kwargs.pop('total_clusters')
        self.pipe_connection: multiprocessing.connection.Connection = cluster_kwargs.pop('pipe')

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        super().__init__(
            loop=loop,
            command_prefix=self.get_prefix,
            case_insensitive=True,
            chunk_guilds_at_startup=False,
            intents=self.allowed_intents,
            owner_ids=set(self.config.owner_ids),
            **cluster_kwargs,

            # getting ready status
            status=discord.Status.dnd,
            activity=discord.Game("Getting ready...")
        )

        # case insensitive cogs
        self._BotBase__cogs = commands.core._CaseInsensitiveDict()

        self.ipc: ipc.IPCClient = None
        self.db: asyncpg.pool.Pool = None
        self.uptime: mido_utils.Time = None

        # set process title so that we can find it like in htop
        setproctitle.setproctitle(str(self))
        self.logger = logging.getLogger(f'{self}')

        self.message_counter = 0
        self.command_counter = 0

        self.http_session: aiohttp.ClientSession | None = None

        self.before_invoke(self.attach_db_objects_to_ctx)

        self.prefix_cache = dict()
        self.webhook_cache: dict[int, discord.Webhook] = dict()

        self.exit_code: int = 1  # 1 == restart me
        self.updated_status: bool = False

        # cog related stuff that should be kept even if cogs restart
        self.active_races: list[Race] = []

        self.run()

    @cached_property
    def allowed_intents(self) -> discord.Intents:
        intents = discord.Intents.all()
        intents.presences = False
        return intents

    @staticmethod
    def get_config(bot_name: str, warn: bool = False) -> models.ConfigFile:
        return models.ConfigFile.get_config(bot_name, warn=warn)

    @property
    def log_channel(self) -> discord.TextChannel | None:
        return self.get_channel(self.config.log_channel_id)

    async def get_prefix(self, message):
        default = self.config.default_prefix

        # "try except" instead of "if else" is better here because it avoids lookup to msg.guild
        try:
            prefixes = commands.when_mentioned_or(self.prefix_cache.get(message.guild.id, default))(self, message)
        except AttributeError:  # if not in guild
            prefixes = commands.when_mentioned_or(default)(self, message)

        # case-insensitive prefix search
        for prefix in prefixes:
            escaped_prefix = re.escape(prefix)
            m = re.compile(f'^({escaped_prefix}).*', flags=re.I).match(message.content)
            if m:
                return m.group(1)

        # if there is not a match, return a random string
        return os.urandom(4).hex()

    async def load_or_reload_cogs(self, cog_name: str = None) -> int:
        """Loads or reloads all cogs or a specified one. Returns the number of loaded/reloaded cogs."""
        cog_counter = 0

        for file in os.listdir("cogs"):
            if not file.endswith(".py"):
                continue

            name = file[:-3]  # strip '.py'

            # if a cog name is provided, and it's not the cog we want, skip
            if cog_name and name != cog_name:
                continue

            self.logger.debug(f"Loading or reloading cog: cogs.{name}")

            try:
                try:
                    await self.reload_extension(f"cogs.{name}")
                    self.logger.info(f"Reloaded cogs.{name}")
                except discord.ext.commands.ExtensionNotLoaded:
                    await self.load_extension(f"cogs.{name}")
                    self.logger.info(f"Loaded cogs.{name}")
            except Exception as e:
                self.logger.error(f"Failed to load cogs.{name}")
                self.logger.exception(e)
            else:
                cog_counter += 1

        self.logger.info(f"Loaded {cog_counter} cogs.")

        return cog_counter

    async def chunk_active_guilds(self):
        await self.wait_until_ready()

        active_guilds = await models.GuildDB.get_guilds_that_are_active_in_last_x_hours(self, hours=6)

        i = 0
        for guild_db in active_guilds:
            guild = self.get_guild(guild_db.id)
            if guild and not guild.chunked:
                await self.chunk_guild(guild)
                i += 1
                await asyncio.sleep(5)

        self.logger.info(f'Chunked {i} active guilds.')

    async def on_ready(self):
        self.logger.info(f'Ready called.')

    def should_listen_to_msg(self, msg: discord.Message, guild_only=False) -> bool:
        return self.is_ready() and not msg.author.bot and (not guild_only or msg.guild)

    async def on_message(self, message: discord.Message):
        if not self.should_listen_to_msg(message):
            return

        self.message_counter += 1

        await self.process_commands(message)

    async def get_context(self, origin: discord.Message | discord.Interaction,
                          cls: Type[commands.Context] = None) -> mido_utils.Context:
        """
        This function overwrites the libraries get_context() function to always use the custom Context class we have.
        """
        return await super().get_context(origin, cls=mido_utils.Context)

    async def process_commands(self, message: discord.Message):
        ctx: mido_utils.Context = await self.get_context(message, cls=mido_utils.Context)

        if ctx.command and ctx.guild and not ctx.guild.chunked:
            await self.chunk_guild(ctx.guild)

        await self.invoke(ctx)

    async def chunk_guild(self, guild: discord.Guild):
        await guild.chunk(cache=True)
        self.logger.info(f'Chunked {guild.member_count if hasattr(guild, "_member_count") else 0} members '
                         f'of guild: {guild.name}')

    async def _guild_announcer(self, guild: discord.Guild, left=False):
        guild_count = await self.ipc.get_guild_count()

        humans = 0
        bots = 0

        for member in guild.members:
            if member.bot:
                bots += 1
            else:
                humans += 1

        keyword = "left" if left else "joined"

        # todo: use the s.sinfo embed
        await self.ipc.send_to_log_channel(
            f"I just {keyword} the guild **{guild.name}** with ID `{guild.id}` [**{bots}** Bots, **{humans}** Humans]. "
            f"Guild counter: {guild_count}")

    async def on_guild_join(self, guild):
        await self._guild_announcer(guild, left=False)

    async def on_guild_remove(self, guild):
        await self._guild_announcer(guild, left=True)

    def log_command(self, ctx: mido_utils.Context, error: Exception = None):
        if isinstance(error, commands.CommandNotFound):
            return

        execution_time = ctx.time_created.passed_seconds_in_float_formatted

        if error:
            log_msg = f"Command errored in {execution_time}:\n"
        else:
            log_msg = f"Command executed successfully in {execution_time}:\n"

        if isinstance(ctx.channel, discord.DMChannel):
            server = "DM"
            channel = f"{ctx.channel.id}"
        else:
            server = f"{ctx.guild.name} ({ctx.guild.id})"
            channel = f"#{ctx.channel.name} ({ctx.channel.id})"

        tab = '\t' * 3
        log_msg += f"{tab}Server\t: {server}\n" \
                   f"{tab}Channel\t: {channel}\n" \
                   f"{tab}User\t: {str(ctx.author)} ({ctx.author.id})\n" \
                   f"{tab}Command\t: {ctx.message.content or '/' + ctx.command.name}"
        if error:
            error_msg = str(error).split('\n')[0] or error.__class__.__name__
            log_msg += f"\n{tab}Error\t: {error_msg}"

        self.logger.info(log_msg)
        self.command_counter += 1

    async def on_command_completion(self, ctx: mido_utils.Context):
        if ctx.guild is not None:
            if ctx.guild_db.delete_commands is True:
                try:
                    await ctx.message.delete()
                except (discord.Forbidden, discord.NotFound):
                    pass

        self.log_command(ctx)

    async def on_command_error(self, ctx: mido_utils.Context, exception):
        self.log_command(ctx, error=exception)

    async def on_error(self, event_method: str, *args, **kwargs):
        await self.get_cog('ErrorHandling').on_error(event_method, *args, **kwargs)

    @staticmethod
    async def attach_db_objects_to_ctx(ctx: mido_utils.Context):
        """
        This func is used as a before_invoke function
        which attaches db objects when a command is about to be called.
        """
        await ctx.defer()  # always defer for commands that take long time to execute
        await ctx.attach_db_objects()

    async def get_user_using_ipc(self, user_id: int) -> discord.User | ipc.SerializedObject | None:
        return super().get_user(user_id) or await self.ipc.get_user(user_id)

    async def send_as_webhook(self, channel: discord.TextChannel, *args, **kwargs):
        try:
            try:
                webhook = self.webhook_cache[channel.id]
            except KeyError:
                try:
                    webhook = self.webhook_cache[channel.id] = next(
                        x for x in await channel.webhooks() if x.name.casefold() == self.user.display_name.casefold())
                except StopIteration:
                    webhook = self.webhook_cache[channel.id] = await channel.create_webhook(name=self.user.display_name)

            await webhook.send(*args, **kwargs, username=self.user.display_name,
                               avatar_url=self.user.display_avatar.url)

        except discord.Forbidden as e:
            # probably no manage webhooks permission
            await channel.send("I need **Manage Webhooks** permission to continue.")
            raise e

        except discord.NotFound:
            # webhook is probably deleted, so delete it from cache as well
            del self.webhook_cache[channel.id]

            self.logger.info(f"The webhook of channel ID {channel.id} could not be found. Retrying...")
            return await self.send_as_webhook(channel, *args, **kwargs)

        except (discord.DiscordServerError,
                aiohttp.ServerDisconnectedError,
                aiohttp.ClientOSError,
                asyncio.TimeoutError,
                discord.HTTPException
                ) as e:
            if mido_utils.better_is_instance(e, discord.HTTPException) and e.status < 500:
                # if it's not a server error and something wrong from our side, raise again
                raise e

            # probably discord servers dying
            self.logger.info(f"There was an error while trying to send a webhook to {channel.id}. Error: {e}\n"
                             f"Retrying...")

            await asyncio.sleep(5.0)
            return await self.send_as_webhook(channel, *args, **kwargs)

        except Exception as e:
            await self.get_cog('ErrorHandling').on_error(str(e))

    @discord.utils.cached_property
    def color(self):
        desired_color_str = self.config.default_embed_color
        if desired_color_str:
            return mido_utils.Color(int(self.config.default_embed_color, 16))
        else:
            return mido_utils.Color.shino_yellow()

    @property
    def status(self):
        """Returns the status of the bot."""
        return self._connection._status

    @status.setter
    def status(self, value=None):
        """Sets the status of the bot which will be automatically refreshed with each identify call"""
        if value:
            if value is discord.Status.offline:
                value = 'invisible'
            else:
                value = str(value)

        self._connection._status = value

    def run(self):
        self.logger.info(f'Preparing the cluster to launch with Shard IDs: {self.shard_ids} ({self.shard_count})')

        try:
            super().run(self.config.token, log_handler=None)
        except discord.PrivilegedIntentsRequired:
            self.logger.error(
                "Apparently you did not enable the Server Members intents "
                "in the developer portal (https://discord.com/developers/applications/). "
                "Please enable them and restart the bot.")

    async def setup_hook(self) -> None:
        self.uptime = mido_utils.Time()
        self.http_session = await mido_utils.MidoBotAPI.get_aiohttp_session()

        # connect to IPC
        self.ipc = ipc.IPCClient(self)

        while not self.db:
            try:
                self.db = await asyncpg.create_pool(**self.config.db_credentials,
                                                    max_inactive_connection_lifetime=60, min_size=5, max_size=10)

            except asyncpg.InvalidCatalogNameError:
                self.logger.warning(
                    f"Looks like a database with name '{self.config.db_credentials['database']}' does not exist. "
                    f"I will create it for you.")

                temp_conn = await asyncpg.connect(**dict(self.config.db_credentials, database='template1'))
                # https://stackoverflow.com/questions/59336747/asyncpg-syntax-error-at-or-near-1-error
                await temp_conn.execute(
                    f'CREATE DATABASE "{self.config.db_credentials["database"]}" '
                    f'OWNER "{self.config.db_credentials["user"]}";')
                await temp_conn.close()

            except Exception:
                self.logger.exception('Error while getting a db connection. Retrying in 5 seconds...')
                await asyncio.sleep(5.0)

            else:
                self.logger.debug("Got DB. Running 'create_table_funcs'")
                await run_create_table_funcs(self)
                break

        self.prefix_cache = dict(await self.db.fetch("""SELECT id, prefix FROM guilds;"""))

        await self.load_or_reload_cogs()

        await self.update_status()

        self.logger.info("Setup hook complete.")
        # await self.chunk_active_guilds()

    async def update_status(self):
        # change the getting ready status
        self.status = discord.Status.online
        self.activity = discord.Game(name=self.config.playing)

        while True:
            try:
                await self.change_presence(status=self.status, activity=self.activity)
            except ConnectionResetError:
                await asyncio.sleep(3.0)
            else:
                self.logger.debug("Updated Discord presence to online.")
                break

    async def close(self):
        await super().close()  # close the bot

        if self.ipc:  # close ipc connection
            await self.ipc.close_ipc(f"Cluster {self.cluster_id} has shut down.")

        if self.db:  # close the db connection
            await self.db.close()

        if self.http_session:  # close the http session
            await self.http_session.close()

        exit(self.exit_code)

    def __str__(self) -> str:
        return f'{self.name.title()} Cluster#{self.cluster_id}'


if __name__ == "__main__":
    ShinobuBot(**{
        'bot_name'      : "midoboto",
        'cluster_id'    : 0,
        'total_clusters': 1,
        'pipe'          : None
    })
