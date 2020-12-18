import json
import logging
import os
import re
from datetime import datetime, timezone

import asyncpg
import discord
from discord.ext import commands

import mido_utils
from models.db import GuildDB, UserDB


class MidoBot(commands.AutoShardedBot):
    # noinspection PyTypeChecker
    def __init__(self, bot_name: str = 'midobot'):
        super().__init__(
            command_prefix=self.get_prefix,
            case_insensitive=True,
            chunk_guilds_at_startup=False,
            intents=discord.Intents.all()
        )

        self.name = bot_name

        self._BotBase__cogs = commands.core._CaseInsensitiveDict()

        with open(f'config_{self.name}.json') as f:
            self.config = json.load(f)

        self.owner_ids = set(self.config['owner_ids'])

        self.first_time = True

        self.db: asyncpg.pool.Pool = None

        self.log_channel = None
        self.logger = logging.getLogger(self.name.title())

        self.message_counter = 0
        self.command_counter = 0
        self.uptime: mido_utils.Time = None

        self.prefix_cache = {}

        self.http_session = mido_utils.MidoBotAPI.get_aiohttp_session()

        self.before_invoke(self.attach_db_objects_to_ctx)

    async def close(self):
        await self.http_session.close()
        await self.db.close()

        await super().close()

    async def prepare_db(self):
        if self.db is None:
            self.db = await asyncpg.create_pool(**self.config['db_credentials'])

    def load_cogs(self):
        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                name = file[:-3]
                try:
                    self.load_extension(f"cogs.{name}")
                    self.logger.info(f"Loaded cogs.{name}")
                except Exception as e:
                    self.logger.error(f"Failed to load cog {name}")
                    self.logger.exception(e)

    async def on_ready(self):
        self.logger.debug("on_ready is called.")

        if self.first_time:
            await self.prepare_db()

            # prefix cache
            self.prefix_cache = dict(await self.db.fetch("""SELECT id, prefix FROM guilds;"""))

            self.load_cogs()

            self.uptime = mido_utils.Time(start_date=datetime.now(timezone.utc))

            self.loop.create_task(self.chunk_active_guilds())

            self.first_time = False
            self.logger.info(f"{self.user} is ready.")

            self.log_channel = self.get_channel(self.config['log_channel_id'])
            await self.log_channel.send("I'm ready!")

        await self.change_presence(status=discord.Status.online, activity=discord.Game(name=self.config["playing"]))

    async def chunk_active_guilds(self):
        active_guilds = await GuildDB.get_guilds_that_are_active_in_last_x_hours(self, 24)

        i = 0
        for guild in active_guilds:
            result = await self.chunk_guild_if_not_chunked(guild.id)
            if result is True:
                i += 1
        self.logger.info(f'Chunked {i} active guilds.')

    async def on_message(self, message: discord.Message):
        if not self.is_ready() or message.author.bot:
            return

        self.message_counter += 1
        if message.guild:
            await GuildDB.just_messaged(self, message.guild.id)

        await self.process_commands(message)

    async def process_commands(self, message):
        ctx: mido_utils.Context = await self.get_context(message, cls=mido_utils.Context)
        if ctx.command and ctx.guild:
            await self.chunk_guild_if_not_chunked(ctx.guild.id)

        await self.invoke(ctx)

    async def chunk_guild_if_not_chunked(self, guild_id: int) -> bool:
        """Chunks the guild if not chunked and returns True if chunk happened."""
        guild: discord.Guild = self.get_guild(guild_id)
        if guild and not guild.chunked:
            self.logger.info(f'Chunking {guild.member_count} members of guild: {guild.name}')
            await guild.chunk(cache=True)
            return True
        return False

    async def on_guild_join(self, guild):
        await self.log_channel.send(
            f"I just joined the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    async def on_guild_remove(self, guild):
        await self.log_channel.send(
            f"I just left the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    def log_command(self, ctx: mido_utils.Context, error: Exception = None):
        if isinstance(error, commands.CommandNotFound):
            return

        execution_time = '{:.2f}s'.format(ctx.time_created.passed_seconds_in_float)

        if error:
            log_msg = f"Command errored in {execution_time}:\n"
        else:
            log_msg = f"Command executed successfully in {execution_time}:\n"

        if isinstance(ctx.channel, discord.DMChannel):
            server = "DM"
            channel = f"{ctx.channel.id}"
        else:
            server = f"{ctx.guild.name} ({ctx.guild.id})"
            channel = f"{ctx.channel.name} ({ctx.channel.id})"

        tab = '\t' * 8
        log_msg += f"{tab}Server\t: {server}\n" \
                   f"{tab}Channel\t: {channel}\n" \
                   f"{tab}User\t: {str(ctx.author)} ({ctx.author.id})\n" \
                   f"{tab}Command\t: {ctx.message.content}"
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
                except discord.Forbidden:
                    pass

        self.log_command(ctx)

    async def on_command_error(self, ctx: mido_utils.Context, exception):
        self.log_command(ctx, error=exception)

    async def get_prefix(self, message):
        default = self.config["default_prefix"]

        # "try except" instead of "if else" is better here because it avoids lookup to msg.guild
        try:
            prefixes = commands.when_mentioned_or(self.prefix_cache.get(message.guild.id, default))(self, message)
        except AttributeError:  # if in guild
            prefixes = commands.when_mentioned_or(default)(self, message)

        # case insensitive prefix search
        for prefix in prefixes:
            escaped_prefix = re.escape(prefix)
            m = re.compile(f'^({escaped_prefix}).*', flags=re.I).match(message.content)
            if m:
                return m.group(1)

        # if there is not a match, return a random string
        return os.urandom(8).hex()

    async def get_user_name(self, _id: int) -> str:
        user_db = await UserDB.get_or_create(bot=self, user_id=_id)
        return user_db.discord_name

    @staticmethod
    async def attach_db_objects_to_ctx(ctx: mido_utils.Context):
        """
        This func is used as a before_invoke function
        which attaches db objects when a command is about to be called.
        """
        await ctx.attach_db_objects()

    def run(self):
        super().run(self.config["token"])
