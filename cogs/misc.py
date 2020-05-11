import ast
import itertools
import os
import time

import discord
import psutil
from discord.ext import commands

from main import MidoBot
from services import checks, time_stuff, context, base_embed


class MyHelpCommand(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(1, 3.0, commands.BucketType.member),
            'help': 'Shows help about the bot or a command.',
            'aliases': ['h']
        })
        self.verify_checks = False

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

        e = base_embed.BaseEmbed(self.context.bot, title='MidoBot Commands')
        for cog, _commands in itertools.groupby(entries, key=key):
            _commands = sorted(_commands, key=lambda c: c.name)
            if len(_commands) == 0:
                continue

            total += len(_commands)
            e.add_field(name=f"**{str(cog)}**",
                        value=", ".join([f'`{c.name}`' for c in _commands]),
                        inline=False)

        await self.context.send(embed=e)

    # async def send_cog_help(self, cog):
    #     entries = await self.filter_commands(cog.get_commands(), sort=True)
    #     pages = HelpPaginator(self, self.context, entries)
    #     pages.title = f'{cog.qualified_name} Commands'
    #     pages.description = cog.description
    #
    #     await self.context.release()
    #     await pages.paginate()

    def common_command_formatting(self, page_or_embed, command):
        page_or_embed.title = self.context.prefix + self.get_command_signature(command)
        if command.description:
            page_or_embed.description = f'{command.description}\n\n{command.help}'
        else:
            page_or_embed.description = command.help or 'No help found...'

    async def send_command_help(self, command):
        embed = base_embed.BaseEmbed(self.context.bot)
        self.common_command_formatting(embed, command)
        await self.context.send(embed=embed)

    # async def send_group_help(self, group):
    #     subcommands = group.commands
    #     if len(subcommands) == 0:
    #         return await self.send_command_help(group)
    #
    #     entries = await self.filter_commands(subcommands, sort=True)
    #     pages = HelpPaginator(self, self.context, entries)
    #     self.common_command_formatting(pages, group)
    #
    #     await self.context.release()
    #     await pages.paginate()


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
        """Evaluates input.
        Input is interpreted as newline seperated statements.
        If the last statement is an expression, that is the return value.
        Usable globals:
          - `bot`: the bot instance
          - `discord`: the discord module
          - `commands`: the discord.ext.commands module
          - `ctx`: the invokation context
          - `__import__`: the builtin `__import__` function
        Such that `>eval 1 + 1` gives `2` as the result.
        The following invokation will cause the bot to send the text '9'
        to the channel of invokation and return '3' as the result of evaluating
        >eval ```
        a = 1 + 2
        b = a * 2
        await ctx.send(a + b)
        a
        ```
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
        """Change or see the prefix. (Administrator permission is required to change the prefix.)"""
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
        """Enable or disable the deletion of commands after completion."""
        new_delete_cmds_status = await ctx.guild_db.toggle_delete_commands()

        if new_delete_cmds_status is True:
            await ctx.send(f"The successful commands will be deleted from now on.")

        else:
            await ctx.send(f"The successful commands will not be deleted from now on.")

    @commands.command(aliases=['info', 'stats'])
    async def about(self, ctx):
        """See some info and stats about me!"""
        mido = self.bot.get_user(self.bot.config['owners'][0])

        uptime = time_stuff.get_time_difference(self.bot, "uptime")

        messages_per_sec = self.bot.message_counter / uptime

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
                        value=time_stuff.parse_seconds(uptime).replace(" ", "\n"),
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


def setup(bot):
    bot.add_cog(Misc(bot))
