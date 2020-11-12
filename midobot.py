import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import discord
import wavelink
from discord.ext import commands

from models.db import MidoTime, UserDB
from services.apis import MidoBotAPI
from services.context import MidoContext


async def _get_prefix(_bot, msg: discord.Message):
    # "try except" instead of "if else" is better here because it avoids lookup to msg.guild
    try:
        return commands.when_mentioned_or(_bot.prefix_cache.get(msg.guild.id, _bot.config["default_prefix"]))(_bot, msg)
    # if in guild
    except AttributeError:
        return commands.when_mentioned_or(_bot.config["default_prefix"])(_bot, msg)


class MidoBot(commands.AutoShardedBot):
    # noinspection PyTypeChecker
    def __init__(self, bot_name: str = "midobot"):
        super().__init__(
            command_prefix=_get_prefix,
            case_insensitive=True,
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
        self.uptime: MidoTime = None

        self.prefix_cache = {}
        self.main_color = 0x15a34a

        self.http_session = MidoBotAPI.get_aiohttp_session()

        self.wavelink: wavelink.Client = None

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
            self.uptime = MidoTime(start_date=datetime.now(timezone.utc))
            self.log_channel = self.get_channel(self.config['log_channel_id'])
            self.logger.info(f"{self.user} is ready.")
            self.first_time = False
            await self.log_channel.send("I'm ready!")

        await self.change_presence(status=discord.Status.online, activity=discord.Game(name=self.config["playing"]))

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=MidoContext)

        await ctx.attach_db_objects()
        await self.invoke(ctx)

    async def on_message(self, message):
        if not self.is_ready() or message.author.bot:
            return

        self.message_counter += 1
        await self.process_commands(message)

    async def on_guild_join(self, guild):
        await self.log_channel.send(
            f"I just joined the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    async def on_guild_remove(self, guild):
        await self.log_channel.send(
            f"I just left the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    def log_command(self, ctx: MidoContext, error: Exception = None):
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
            log_msg += f"\n{tab}Error: {error_msg}"

        self.logger.info(log_msg)
        self.command_counter += 1

    async def on_command_completion(self, ctx: MidoContext):
        if ctx.guild is not None:
            if ctx.guild_db.delete_commands is True:
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass

        self.log_command(ctx)

    async def on_command_error(self, ctx: MidoContext, exception):
        self.log_command(ctx, error=exception)

    async def get_user_name(self, _id: int) -> str:
        user_db = await UserDB.get_or_create(bot=self, user_id=_id)
        return user_db.discord_name

    def run(self):
        super().run(self.config["token"])
