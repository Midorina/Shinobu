import ast
import itertools
import os
import time
from datetime import timezone, datetime, timedelta

import discord
import psutil
from discord.ext import commands

from db.models import MidoTime
from main import MidoBot
from services import checks, context, base_embed


class MyHelpCommand(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(rate=1, per=1.0, type=commands.BucketType.member),
            'help': 'Shows help about the bot or a command.',
            'aliases': ['h']
        })
        self.verify_checks = False

    # overriding this for additional prefix check
    async def command_callback(self, ctx, *, command=None):
        await self.prepare_help_command(ctx, command)
        bot = ctx.bot

        if command is None:
            mapping = self.get_bot_mapping()
            return await self.send_bot_help(mapping)

        # Check if it's a cog
        cog = bot.get_cog(command)
        if cog is not None:
            return await self.send_cog_help(cog)

        maybe_coro = discord.utils.maybe_coroutine

        # If it's not a cog then it's a command.
        # Since we want to have detailed errors when someone
        # passes an invalid subcommand, we need to walk through
        # the command group chain ourselves.
        keys = command.split(' ')

        # maybe it has a prefix at the beginning
        prefix_length = len(self.context.prefix)
        if keys[0][:prefix_length] == self.context.prefix:
            keys[0] = keys[0][prefix_length:]

        cmd = bot.all_commands.get(keys[0])
        if cmd is None:
            string = await maybe_coro(self.command_not_found, self.remove_mentions(keys[0]))
            return await self.send_error_message(string)

        for key in keys[1:]:
            try:
                found = cmd.all_commands.get(key)
            except AttributeError:
                string = await maybe_coro(self.subcommand_not_found, cmd, self.remove_mentions(key))
                return await self.send_error_message(string)
            else:
                if found is None:
                    string = await maybe_coro(self.subcommand_not_found, cmd, self.remove_mentions(key))
                    return await self.send_error_message(string)
                cmd = found

        if isinstance(cmd, commands.Group):
            return await self.send_group_help(cmd)
        else:
            return await self.send_command_help(cmd)

    def command_not_found(self, string):
        return f'Couldn\'t find any command called `{string}`'

    async def on_help_command_error(self, ctx: context.Context, error):
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(str(error.original))

    def get_command_signature(self, command):
        parent = command.full_parent_name

        if len(command.aliases) > 0:
            aliases = '|'.join(command.aliases)
            fmt = f'[{command.name}|{aliases}]'
            if parent:
                fmt = f'{parent} {fmt}'
            alias = fmt
        else:
            alias = command.name if not parent else f'{parent} {command.name}'

        return f'{alias} {command.signature}'

    async def send_bot_help(self, mapping):
        def key(c):
            return c.cog_name or '\u200bNo Category'

        entries = await self.filter_commands(self.context.bot.commands, sort=True, key=key)
        total = 0

        e = base_embed.BaseEmbed(self.context.bot,
                                 title='MidoBot Commands',
                                 description=f'You can type `{self.context.prefix}help <command>` '
                                             f'to see additional info about a command.')
        for cog, _commands in itertools.groupby(entries, key=key):
            _commands = sorted(_commands, key=lambda c: c.name)
            if len(_commands) == 0:
                continue

            total += len(_commands)
            e.add_field(name=f"**__{str(cog)}__**",
                        value="\n".join([f'`{self.context.prefix}{c.name}`' for c in _commands]),
                        inline=True)

        await self.context.send(embed=e)

    def common_command_formatting(self, embed, command):
        embed.title = self.context.prefix + self.get_command_signature(command)
        if command.description:
            embed.description = f'{command.description}\n\n{command.help}'
        else:
            if not command.help:
                embed.description = 'There\'s no help information about this command...'
            else:
                embed.description = command.help.format(self.context)

    async def send_command_help(self, command):
        if command.hidden:
            raise commands.CommandInvokeError("That is a hidden command. Sorry.")

        embed = base_embed.BaseEmbed(self.context.bot)
        self.common_command_formatting(embed, command)
        await self.context.send(embed=embed)


def insert_returns(body):
    # insert return stmt if the last expression is a expression statement
    if isinstance(body[-1], ast.Expr):
        body[-1] = ast.Return(body[-1].value)
        ast.fix_missing_locations(body[-1])

    # for if statements, we insert returns into the body and the orelse
    if isinstance(body[-1], ast.If):
        insert_returns(body[-1].body)
        insert_returns(body[-1].orelse)

    # for with blocks, again we insert returns into the body
    if isinstance(body[-1], ast.With):
        insert_returns(body[-1].body)


class Misc(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot
        self.old_help_command = bot.help_command
        bot.help_command = MyHelpCommand()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self.old_help_command

    @commands.command(hidden=True)
    @checks.owner_only()
    async def eval(self, ctx, *, cmd):
        """A developer command that evaluates code.

        Globals:
          - `bot`: the bot instance
          - `discord`: the discord module
          - `commands`: the discord.ext.commands module
          - `ctx`: the invokation context
          - `__import__`: the builtin `__import__` function
        """
        fn_name = "_eval_expr"

        cmd = cmd.strip("`py ")

        # add a layer of indentation
        cmd = "\n".join(f"    {i}" for i in cmd.splitlines())

        # wrap in async def body
        body = f"async def {fn_name}():\n{cmd}"

        parsed = ast.parse(body)
        body = parsed.body[0].body

        insert_returns(body)

        env = {
            'bot': ctx.bot,
            'discord': discord,
            'commands': commands,
            'ctx': ctx,
            '__import__': __import__
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = await eval(f"{fn_name}()", env)
        await ctx.send(result)

    @commands.command()
    async def ping(self, ctx: context.Context):
        """Ping me to check the latency!"""
        if ctx.guild:
            color = ctx.guild.me.top_role.color
        else:
            color = discord.Colour.dark_grey()

        before = time.monotonic()

        embed_msg = discord.Embed(title="Ping!", description=f"Latency: `... ms`", color=color)
        message = await ctx.send(embed=embed_msg)

        ping = (time.monotonic() - before) * 1000
        new_embed_msg = discord.Embed(title="🏓 Pong!", description=f"Latency: `{int(ping)} ms`", color=color)

        await message.edit(embed=new_embed_msg)

    @commands.guild_only()
    @commands.command()
    async def prefix(self, ctx: context.Context, *, prefix: str = None):
        """See or change the prefix.

        You need the **Administrator** permission to change the prefix.
        """
        if prefix:
            if not ctx.author.guild_permissions.administrator:
                raise commands.CheckFailure

            await ctx.guild_db.change_prefix(prefix)

            # update cache
            self.bot.prefix_cache[ctx.guild.id] = prefix

            return await ctx.send(f"The prefix has been successfully changed to `{prefix}`")
        else:
            return await ctx.send(f"Current prefix for this server: `{ctx.prefix}`")

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.command(name="deletecommands", aliases=["delcmds"])
    async def delete_commands(self, ctx: context.Context):
        """Enable or disable the deletion of commands after completion.

        You need the **Administrator** permission to use this command.
        """
        new_delete_cmds_status = await ctx.guild_db.toggle_delete_commands()

        if new_delete_cmds_status is True:
            await ctx.send(f"The successful commands will be deleted from now on.")

        else:
            await ctx.send(f"The successful commands will not be deleted from now on.")

    @commands.command(aliases=['info', 'stats'])
    async def about(self, ctx):
        """See some info and stats about me!
        """
        mido = self.bot.get_user(self.bot.config['owners'][0])

        uptime_in_seconds = (datetime.now(timezone.utc) - self.bot.uptime) / timedelta(seconds=1)

        messages_per_sec = self.bot.message_counter / uptime_in_seconds

        memory = psutil.virtual_memory()[3] >> 20

        embed = discord.Embed(color=self.bot.main_color)

        embed.description = f"I'm a general purpose bot that features various stuff! " \
                            f"Type `{ctx.prefix}help` to learn more.\n\n" \
                            f"[Click here to invite me to your server!]({self.bot.config['invite_link']})"

        embed.set_author(name=f"{self.bot.user}",
                         icon_url=self.bot.user.avatar_url,
                         url=self.bot.config['website'])

        embed.add_field(name="Owner",
                        value=f"{str(mido)}\n"
                              f"(439632807770325012)",
                        inline=True)

        embed.add_field(name="Guild Count",
                        value=str(len(self.bot.guilds)),
                        inline=True)

        embed.add_field(name="Messages",
                        value=f"{self.bot.message_counter}\n({round(messages_per_sec, 2)}/sec)",
                        inline=True)

        embed.add_field(name="Memory",
                        value=str(memory) + " MB",
                        inline=True)

        embed.add_field(name="Commands ran",
                        value=self.bot.command_counter,
                        inline=True)

        embed.add_field(name="Uptime",
                        value=MidoTime.parse_seconds_to_str(uptime_in_seconds),
                        inline=True)

        embed.set_footer(icon_url=mido.avatar_url,
                         text=f"Made by {mido} with love ♥")

        await ctx.send(embed=embed)

    @commands.command(hidden=True)
    @checks.owner_only()
    async def reload(self, ctx):
        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                name = file[:-3]
                try:
                    self.bot.reload_extension(f"cogs.{name}")
                except discord.ext.commands.ExtensionNotLoaded:
                    self.bot.load_extension(f"cogs.{name}")

        await ctx.send("Successfully reloaded all cogs!")

    @commands.command(hidden=True)
    @checks.owner_only()
    async def shutdown(self, ctx):
        await ctx.send("Shutting down...")

        await self.bot.logout()


def setup(bot):
    bot.add_cog(Misc(bot))
