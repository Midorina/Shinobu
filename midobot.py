import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import discord
import wavelink
from discord.ext import commands

from models.db_models import MidoTime, UserDB
from services.apis import MidoBotAPI
from services.context import MidoContext


async def _get_prefix(_bot, msg: discord.Message):
    # "try except" instead of "if else" is better here because it avoids lookup to msg.guild
    try:
        return commands.when_mentioned_or(_bot.prefix_cache.get(msg.guild.id, _bot.config["default_prefix"]))(_bot, msg)
    # if in guild
    except AttributeError:
        return commands.when_mentioned_or(_bot.config["default_prefix"])(_bot, msg)


intents = discord.Intents.default()
# intents.members = True
# intents.presences = True


class MidoBot(commands.AutoShardedBot):
    # noinspection PyTypeChecker
    def __init__(self, bot_name: str = "midobot"):
        super().__init__(
            command_prefix=_get_prefix,
            case_insensitive=True,
            intents=intents
        )

        self._BotBase__cogs = commands.core._CaseInsensitiveDict()

        with open(f'config_{bot_name}.json') as f:
            self.config = json.load(f)

        self.first_time = True

        self.db: asyncpg.pool.Pool = None

        self.log_channel = None
        self.logger = logging.getLogger('Shinobu')

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

        if ctx.command is None:
            return

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

    @staticmethod
    async def on_command_completion(ctx):
        if ctx.guild is not None:
            if ctx.guild_db.delete_commands is True:
                try:
                    await ctx.message.delete()
                except discord.Forbidden:
                    pass

    async def on_command(self, ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            server = "DM"
            channel = f"{ctx.channel.id}"
        else:
            server = f"{ctx.guild.name} ({ctx.guild.id})"
            channel = f"{ctx.channel.name} ({ctx.channel.id})"

        self.logger.info(f"Command executed:\n"
                         f"Server\t: {server}\n"
                         f"Channel\t: {channel}\n"
                         f"User\t: {str(ctx.author)} ({ctx.author.id})\n"
                         f"Command\t: {ctx.message.content}"
                         )

        self.command_counter += 1

    async def get_user_name(self, _id: int, user_db: UserDB = None):
        user = self.get_user(_id)
        if user:
            return str(user)
        else:
            user_db = user_db or await UserDB.get_or_create(self.db, _id)
            return user_db.discord_name

    def run(self):
        super().run(self.config["token"])
