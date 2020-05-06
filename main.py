import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import discord
from discord.ext import commands

from db import db_funcs
from services import context


# TODO: prefix cache


async def _get_prefix(_bot, msg: discord.Message):
    if msg.guild is None:
        prefix = _bot.config["default_prefix"]

    else:
        guild_db = await db_funcs.get_guild_db(_bot.db, msg.guild.id)
        prefix = guild_db.prefix

    return commands.when_mentioned_or(prefix)(_bot, msg)


class MidoBot(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(
            command_prefix=_get_prefix,
            case_insensitive=True
        )

        with open('config.json') as f:
            self.config = json.load(f)

        self.first_time = True

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
            self.load_cogs()
            self.uptime = datetime.now(timezone.utc)
            self.log_channel = self.get_channel(self.config['log_channel'])
            self.logger.info(f"{self.user} is ready.")
            self.first_time = False
            await self.log_channel.send("I'm ready!")

        await self.change_presence(status=discord.Status.online, activity=discord.Game(name=self.config["playing"]))

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=context.Context)

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
        await db_funcs.insert_new_guild(self.db, guild.id)
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

    def run(self):
        self.remove_command("help")
        super().run(self.config["token"])
