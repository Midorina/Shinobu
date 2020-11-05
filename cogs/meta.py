import ast
import multiprocessing
import os
import time
from datetime import datetime

import discord
import psutil
from discord.ext import commands, commands, tasks

from midobot import MidoBot
from models.db_models import UserDB
from services import checks
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError
from services.resources import Resources
from services.time_stuff import MidoTime


class MidoHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(rate=1, per=1.0, type=commands.BucketType.member),
            'help'    : 'Shows help about the bot or a command.',
            'aliases' : ['h']
        })
        self.verify_checks = False

    def command_not_found(self, string):
        return f'Couldn\'t find any command called `{string}`'

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

    async def send_bot_help(self, cogs_and_commands):
        e = MidoEmbed(self.context.bot,
                      title='Shinobu Command Modules',
                      description=f'You can type `{self.context.prefix}help <module>` '
                                  f'to see the commands that are in that module.\n\n'
                                  f'Feel free to join the [support server]({Resources.links.support_server}) if you need additional help.',
                      default_footer=True)

        cogs = sorted(cogs_and_commands.keys(), key=lambda x: str(x))

        cmd_counter = 0
        for cog in cogs:
            if cog and len(cog.get_commands()) > 0:
                cmd_counter_cog = len(cog.get_commands())
                cmd_counter += cmd_counter_cog

                e.add_field(name=f'__{cog.qualified_name}__', value=f'{cmd_counter_cog} Commands')

        e.set_footer(text=f"{cmd_counter} Commands",
                     icon_url=self.context.bot.user.avatar_url)
        e.timestamp = datetime.utcnow()

        await self.context.send(embed=e)

    async def send_cog_help(self, cog):
        def chunks(lst, n):
            for j in range(0, len(lst), n):
                yield lst[j:j + n]

        _commands = await self.filter_commands(cog.get_commands(), sort=True)

        e = MidoEmbed(self.context.bot,
                      title=f'Shinobu {cog.qualified_name} Commands',
                      description=f'You can type `{self.context.prefix}help <command>` '
                                  f'to see additional info about a command.',
                      default_footer=True)

        for i, chunk in enumerate(chunks(_commands, 5), 1):
            e.add_field(name=f"Command List {i}",
                        value="\n".join([f'● {self.context.prefix}`{c.name}`' for c in chunk]),
                        inline=True)

        e.set_footer(text=f"{len(_commands)} Commands",
                     icon_url=self.context.bot.user.avatar_url)
        e.timestamp = datetime.utcnow()

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

    async def send_command_help(self, command, content=''):
        if command.hidden:
            raise commands.CommandInvokeError("That is a hidden command. Sorry.")

        embed = MidoEmbed(self.context.bot, default_footer=True)
        self.common_command_formatting(embed, command)
        await self.context.send(content=content, embed=embed)


class Misc(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.process = psutil.Process(os.getpid())

        # help command
        self.old_help_command = bot.help_command
        bot.help_command = MidoHelp()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self.old_help_command

    @tasks.loop(minutes=10)
    async def update_name_cache(self):
        for user_db in await UserDB.get_all(self.bot.db):
            user = self.bot.get_user(user_db.id)
            if user and str(user) != user_db.discord_name:
                await user_db.update_name(str(user))

        self.bot.logger.info('Updated the name cache of users.')

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

        def insert_returns(_body):
            # insert return stmt if the last expression is a expression statement
            if isinstance(_body[-1], ast.Expr):
                _body[-1] = ast.Return(_body[-1].value)
                ast.fix_missing_locations(_body[-1])

            # for if statements, we insert returns into the body and the orelse
            if isinstance(_body[-1], ast.If):
                insert_returns(_body[-1].body)
                insert_returns(_body[-1].orelse)

            # for with blocks, again we insert returns into the body
            if isinstance(_body[-1], ast.With):
                insert_returns(_body[-1].body)

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
            'bot'       : ctx.bot,
            'discord'   : discord,
            'commands'  : commands,
            'ctx'       : ctx,
            '__import__': __import__
        }
        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        result = await eval(f"{fn_name}()", env)
        await ctx.send(result)

    @commands.command()
    async def ping(self, ctx: MidoContext):
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
    async def prefix(self, ctx: MidoContext, *, prefix: str = None):
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
    async def delete_commands(self, ctx: MidoContext):
        """Enable or disable the deletion of commands after completion.

        You need the **Administrator** permission to use this command.
        """
        new_delete_cmds_status = await ctx.guild_db.toggle_delete_commands()

        if new_delete_cmds_status is True:
            await ctx.send(f"The successful commands will be deleted from now on.")

        else:
            await ctx.send(f"The successful commands will not be deleted from now on.")

    @commands.command(aliases=['info', 'about'])
    async def stats(self, ctx: MidoContext):
        """See some info and stats about me!"""
        mido = self.bot.get_user(self.bot.config['owner_ids'][0])

        memory = self.process.memory_info().rss / 10 ** 6

        embed = discord.Embed(color=self.bot.main_color)

        embed.description = f"I'm a general purpose bot that features various features! " \
                            f"Type `{ctx.prefix}help` to learn more.\n\n" \
                            f"**I've recently got a rewrite, so some features are missing.**\n" \
                            f"Additionally, I am not verified yet. " \
                            f"So, you can't invite me to new servers until I get verified.\n\n" \
                            f"Join the [support server]({Resources.links.support_server}) " \
                            f"if you want to provide feedback, get the latest news and join donut events."

        embed.set_author(name=f"{self.bot.user}",
                         icon_url=self.bot.user.avatar_url,
                         url=Resources.links.website)

        embed.add_field(name="Uptime",
                        value=MidoTime.parse_seconds_to_str(self.bot.uptime.remaining_seconds, sep='\n'),
                        inline=True)

        embed.add_field(name="Discord Stats",
                        value=f"{len(self.bot.guilds)} Guilds\n"
                              f"{len([channel for guild in self.bot.guilds for channel in guild.channels])} Channels\n"
                              f"{sum([guild.member_count for guild in self.bot.guilds])} Members",
                        inline=True)

        # embed.add_field(name="Message Count",
        #                 value=f"{self.bot.message_counter} Messages\n"
        #                       f"{self.bot.command_counter} Commands",
        #                 inline=True)

        embed.add_field(name="Performance",
                        value="Music Players: {}\n"
                              "CPU: {}%\n"
                              "Memory: {:.2f} MB\n".format(len(self.bot.wavelink.players),
                                                           self.process.cpu_percent(interval=1),
                                                           memory),
                        inline=True)

        if mido:  # intents disabled
            embed.set_footer(icon_url=mido.avatar_url,
                             text=f"Made by {mido} with love ♥")

        await ctx.send(embed=embed)

    @commands.command(hidden=True)
    @checks.owner_only()
    async def reload(self, ctx, cog_name: str = None):
        cog_counter = 0
        for file in os.listdir("cogs"):
            if file.endswith(".py"):
                name = file[:-3]

                # if a cog name is provided, and its not the cog we want, skip
                if cog_name and name != cog_name:
                    continue

                try:
                    self.bot.reload_extension(f"cogs.{name}")
                except discord.ext.commands.ExtensionNotLoaded:
                    self.bot.load_extension(f"cogs.{name}")
                finally:
                    cog_counter += 1

        await ctx.send(f"Successfully reloaded **{cog_counter}** cog(s)!")

    @commands.command(hidden=True)
    @checks.owner_only()
    async def shutdown(self, ctx, *, force: str = None):
        await ctx.send("Shutting down...")

        if force == '-f':
            multiprocessing.Process(target=os.system, args=('pm2 stop midobot',)).start()

        await self.bot.close()

    @checks.owner_only()
    @commands.command(hidden=True)
    async def setavatar(self, ctx, new_av: str = None):
        if new_av:
            av_link = new_av

        else:
            if ctx.message.attachments:
                av_link = ctx.message.attachments[0].url
            else:
                return await ctx.send("You have to either attach an image to your message or give a picture URL!")

        async with self.bot.http_session.get(av_link) as r:
            if r.status == 200:
                img_bytes = await r.read()
            else:
                raise EmbedError("Invalid URL!")

        await self.bot.user.edit(avatar=img_bytes)
        await ctx.send("Avatar has been successfully updated.")

    @commands.command()
    async def invite(self, ctx: MidoContext):
        e = MidoEmbed(self.bot)
        e.title = f"Invite {self.bot.user} to your server:"
        e.description = f"[With Administrator Permission]({Resources.links.invite_admin}) (Suggested)\n" \
                        f"[With Minimal Permissions]({Resources.links.invite_minimal})\n" \
                        f"[With Selectable Permissions]({Resources.links.invite_selectable})\n" \
                        f"[With No Permission]({Resources.links.invite_none})"
        e.set_thumbnail(url=self.bot.user.avatar_url)

        await ctx.send(embed=e)

    @commands.command()
    async def say(self, ctx: MidoContext, *, message: str):
        """Make me say something."""
        # commands.clean_content is not used, because the message will be shown in an embed.
        await ctx.send_success(message)

    @commands.command(aliases=['erasedata'])
    async def deletedata(self, ctx: MidoContext):
        """Delete all of your data from Shinobu."""
        e = MidoEmbed(bot=self.bot,
                      description="Are you sure you'd like to erase all of your data?\n\n"
                                  "**This action is irreversible.**")

        msg = await ctx.send(embed=e)

        yes = await MidoEmbed.yes_no(bot=self.bot, author_id=ctx.author.id, msg=msg)
        if yes:
            await ctx.user_db.delete()

            await ctx.edit_custom(msg, "Your data has been successfully erased.")
        else:
            await ctx.edit_custom(msg, "Request declined.")


def setup(bot):
    bot.add_cog(Misc(bot))
