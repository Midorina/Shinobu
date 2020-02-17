import logging
import os
import discord
import json
import asyncpg

from discord.ext import commands
from discord.ext.commands import AutoShardedBot
from datetime import datetime

from services import db_funcs


async def _get_prefix(_bot, msg: discord.Message):
    if msg.guild is None:
        prefix = _bot.config["default_prefix"]

    else:
        guild_db = await db_funcs.get_guild_db(_bot.db, msg.guild.id)
        prefix = guild_db.prefix

    return commands.when_mentioned_or(prefix)(_bot, msg)


class MidoBot(AutoShardedBot):
    def __init__(self):
        super().__init__(
            command_prefix=_get_prefix,
            case_insensitive=True
        )

        with open('config.json') as f:
            self.config = json.load(f)

        self.db = None
        self.log_channel = None
        self.logger = logging.getLogger('MidoBot')

        self.message_counter = 0
        self.command_counter = 0
        self.uptime = None

    async def close(self):
        await self.db.close()
        await super().close()

    async def prepare_db(self):
        if self.db is None:
            self.db = await asyncpg.create_pool(**self.config['db_credentials'])

    async def on_ready(self):
        # if not discord.opus.is_loaded():
        #     opus_name = ctypes.util.find_library('libopus')
        #     if opus_name is None:
        #         self.logger.error('Failed to find the Opus library.')
        #     else:
        #         discord.opus.load_opus(opus_name)

        await self.prepare_db()

        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                name = file[:-3]
                try:
                    self.load_extension(f"cogs.{name}")
                    self.logger.info(f"Loaded cogs.{name}")
                except Exception as e:
                    self.logger.error(f"Failed to load cog {name}")
                    self.logger.exception(e)

        self.uptime = datetime.utcnow()

        await self.change_presence(status=discord.Status.online, activity=discord.Game(name=self.config["playing"]))

        self.logger.info(f"{self.user} is ready.")

        self.log_channel = self.get_channel(self.config['log_channel'])
        await self.log_channel.send("I'm ready!")

    async def on_message(self, message):
        if not self.is_ready():
            return

        if message.author.bot:
            return

        self.message_counter += 1
        await self.process_commands(message)

    # async def process_commands(self, message):
    #     ctx = await self.get_context(message, cls=context.Context)
    #     await ctx.init()
    #
    #     if ctx.command is None:
    #         return
    #
    #     # if ctx.author.id in self.blacklist:
    #     #     return
    #     #
    #     # if ctx.guild is not None and ctx.guild.id in self.blacklist:
    #     #     return
    #
    #     await self.invoke(ctx)

    async def on_guild_join(self, guild):
        await db_funcs.insert_new_guild(self.db, guild.id)

        await self.log_channel.send(
            f"I just joined the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    async def on_guild_remove(self, guild):
        await self.log_channel.send(
            f"I just left the guild **{guild.name}** with ID `{guild.id}`. Guild counter: {len(self.guilds)}")

    async def on_command_completion(self, ctx):
        if ctx.guild is not None:
            guild_db = await db_funcs.get_guild_db(self.db, ctx.guild.id)

            if guild_db.delete_commands is True:
                try:
                    await ctx.message.delete()
                except:
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

    def run(self):
        self.remove_command("help")
        super().run(self.config["token"])
