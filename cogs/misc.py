import ast
import multiprocessing
import os
import time

import discord
import psutil
from discord.ext import commands, tasks

from midobot import MidoBot
from models.db_models import UserDB
from services import checks
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError
from services.resources import Resources
from services.time_stuff import MidoTime


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

        self.process = psutil.Process(os.getpid())
        self.update_name_cache.start()

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

    @commands.command(aliases=['info', 'stats'])
    async def about(self, ctx: MidoContext):
        """See some info and stats about me!"""
        mido = self.bot.get_user(self.bot.config['owners'][0])

        memory = self.process.memory_info().rss / 10 ** 6

        embed = discord.Embed(color=self.bot.main_color)

        embed.description = f"I'm a general purpose bot that features various stuff! " \
                            f"Type `{ctx.prefix}help` to learn more.\n\n"

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

        embed.add_field(name="Message Count",
                        value=f"{self.bot.message_counter} Messags\n"
                              f"{self.bot.command_counter} Commands",
                        inline=True)

        embed.add_field(name="Performance",
                        value="Music Players: {}\n"
                              "CPU: {}%\n"
                              "Memory: {:.2f} MB\n".format(len(self.bot.get_cog('Music').voice_states),
                                                           self.process.cpu_percent(interval=1),
                                                           memory),
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


def setup(bot):
    bot.add_cog(Misc(bot))
