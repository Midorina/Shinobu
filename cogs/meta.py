import ast
import os
import traceback
from datetime import datetime

import discord
import psutil
from discord.ext import commands

import mido_utils
from shinobu import ShinobuBot


# TODO: place commands under groups and overhaul the help command according to that
class MidoHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(rate=1, per=1.0, type=commands.BucketType.member),
            'help'    : 'Shows help about the bot or a command.',
            'aliases' : ['h']
        })
        self.verify_checks = False

    def command_not_found(self, string):
        raise commands.UserInputError(f"There isn't any command called `{string}`.")

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
        bot = self.context.bot

        e = mido_utils.Embed(
            bot,
            title=f'{bot.user.name} Command Modules',
            description=f"You can type `{self.context.prefix}invite` to invite me to your server.\n"
                        f"\n"
                        f'You can type `{self.context.prefix}help <module>` '
                        f'to see the commands that are in that module.\n'
                        f'\n'
                        f'Feel free to join the [support server]({mido_utils.links.support_server}) '
                        f'if you need additional help.',
            default_footer=True
        )

        cogs = filter(lambda y: y is not None, sorted(cogs_and_commands.keys(), key=lambda x: str(x)))

        cmd_counter = 0
        for cog in cogs:
            _commands = await self.filter_commands(cog.get_commands(), sort=True)

            if len(_commands) > 0:
                cmd_counter_cog = len(_commands)
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
        if len(_commands) == 0:
            raise commands.CheckFailure("That is a hidden module. Sorry.")

        description = cog.description.format(ctx=self.context, bot=self.context.bot, mido_utils=mido_utils)

        e = mido_utils.Embed(self.context.bot,
                             title=f'{cog.qualified_name} Commands',
                             description=
                             f'{description}\n\n'
                             f'You can type `{self.context.prefix}help <command>` '
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
                embed.description = command.help.format(ctx=self.context, bot=self.context.bot, mido_utils=mido_utils)

        embed.set_footer(text=f'{command.cog.qualified_name} Module', icon_url=self.context.bot.user.avatar_url)
        embed.timestamp = datetime.utcnow()

    async def send_command_help(self, command, content=''):
        if command.hidden:
            raise commands.CheckFailure("That is a hidden command. Sorry.")

        embed = mido_utils.Embed(self.context.bot)
        self.common_command_formatting(embed, command)
        await self.context.send(content=content, embed=embed)


class Meta(commands.Cog,
           description='Use `{ctx.prefix}prefix` to change the way you call me, '
                       '`{ctx.prefix}invite` to get invite links and '
                       '`{ctx.prefix}deletedata` to delete everything I know about you.'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.process = psutil.Process(os.getpid())

        # help command
        self.old_help_command = bot.help_command
        bot.help_command = MidoHelp()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self.old_help_command

    async def _eval(self, cmd, ctx=None):
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
            'bot'       : self.bot,
            'discord'   : discord,
            'commands'  : commands,
            '__import__': __import__
        }
        if ctx:
            env['ctx'] = ctx

        exec(compile(parsed, filename="<ast>", mode="exec"), env)

        try:
            result = await eval(f"{fn_name}()", env) or 'None'
        except Exception as e:
            result = e
            traceback.print_exc()

        return result

    @commands.command(hidden=True)
    @mido_utils.is_owner()
    async def eval(self, ctx, *, cmd):
        """A developer command that evaluates code.

        Globals:
          - `bot`: the bot instance
          - `discord`: the discord module
          - `commands`: the discord.ext.commands module
          - `ctx`: the invocation context
          - `__import__`: the builtin `__import__` function
        """
        await ctx.send(await self._eval(cmd, ctx))

    @commands.command()
    async def ping(self, ctx: mido_utils.Context):
        """Ping me to check the latency!"""
        color = ctx.guild.me.top_role.color if ctx.guild else self.bot.color

        cluster_stats = await self.bot.ipc.get_cluster_stats()

        embed_msg = mido_utils.Embed(bot=ctx.bot,
                                     title='Ping!',
                                     description='',
                                     color=color,
                                     default_footer=True)

        for cluster in cluster_stats:
            # this is to avoid overflow
            latency = float(f"{cluster.latency:.3f}")

            latency = mido_utils.readable_bigint(latency * 1000)
            embed_msg.description += f'Cluster**#{cluster.author}**: **Pong! 🏓** | `{latency} ms`\n'

        await ctx.send(embed=embed_msg)

    @commands.guild_only()
    @commands.command()
    async def prefix(self, ctx: mido_utils.Context, *, prefix: str = None):
        """Provide no arguments to see the prefix.
        Specify one to change the server's prefix.

        You need the **Administrator** permission to change the prefix.
        """
        if prefix:
            if not ctx.author.guild_permissions.administrator:
                raise commands.CheckFailure("You need Administrator permission to change the prefix.")

            await ctx.guild_db.change_prefix(prefix)

            await ctx.send_success(f"The prefix has been successfully changed to: `{prefix}`\n\n"
                                   f"*My prefixes are case insensitive.*")
        else:
            await ctx.send_success(f"Current prefix for this server: `{ctx.prefix}`\n\n"
                                   f"*My prefixes are case insensitive.*")

    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.command(name="deletecommands", aliases=["delcmds"])
    async def delete_commands(self, ctx: mido_utils.Context):
        """Enable or disable the deletion of commands after completion.

        You need the **Administrator** permission to use this command.
        """
        new_delete_cmds_status = await ctx.guild_db.toggle_delete_commands()

        if new_delete_cmds_status is True:
            await ctx.send(f"The successful commands will be deleted from now on.")

        else:
            await ctx.send(f"The successful commands will not be deleted from now on.")

    @commands.command(aliases=['info', 'about', 'botinfo'])
    async def stats(self, ctx: mido_utils.Context):
        """See some info and stats about me!"""
        mido = await self.bot.get_user_using_ipc(90076279646212096)

        cluster_stats = await self.bot.ipc.get_cluster_stats()

        embed = mido_utils.Embed(bot=ctx.bot)

        embed.description = f"I'm a general purpose bot that provides various features!\n" \
                            f"\n" \
                            f"**Type `{ctx.prefix}invite` to invite me** to your server.\n" \
                            f"**Type `{ctx.prefix}help` to get help** about commands.\n" \
                            f"\n" \
                            f"Join the [support server]({mido_utils.links.support_server}) " \
                            f"if you would like to provide feedback, " \
                            f"get the latest news and/or join {mido_utils.emotes.currency} events.\n\n" \
                            f"I am open sourced. Check out my code -> {mido_utils.resources.links.github}"

        embed.set_author(name=f"{self.bot.user}",
                         icon_url=self.bot.user.avatar_url,
                         url=mido_utils.links.website)

        embed.add_field(name="Uptime",
                        value=mido_utils.Time.parse_seconds_to_str(self.bot.uptime.remaining_seconds, sep='\n'),
                        inline=True)

        guild_count = mido_utils.readable_bigint(sum(x.guilds for x in cluster_stats))
        channel_count = mido_utils.readable_bigint(sum(x.channels for x in cluster_stats))
        member_count = mido_utils.readable_bigint(sum(x.members for x in cluster_stats))
        embed.add_field(name="Discord Stats",
                        value=f"{guild_count} Guilds\n"
                              f"{channel_count} Channels\n"
                              f"{member_count} Members",
                        inline=True)

        # embed.add_field(name="Message Count",
        #                 value=f"{self.bot.message_counter} Messages\n"
        #                       f"{self.bot.command_counter} Commands",
        #                 inline=True)

        music_players = mido_utils.readable_bigint(sum(x.music_players for x in cluster_stats))
        memory = mido_utils.readable_bigint(sum(x.memory for x in cluster_stats), small_precision=True)

        cpu_usages = [x.cpu_usage for x in cluster_stats]
        try:
            average_cpu = sum(cpu_usages) / len(cpu_usages)
        except ZeroDivisionError:
            average_cpu = 0

        embed.add_field(name="Performance",
                        value=f"Clusters: {len(cluster_stats)}/{self.bot.cluster_count}\n"
                              f"Average CPU: {average_cpu:.2f}%\n"
                              f"Total Memory: {memory} MB\n"
                              f"Music Players: {music_players}\n",
                        inline=True)

        if mido:  # intents disabled
            embed.set_footer(icon_url=mido.avatar_url,
                             text=f"Made by {mido.display_name} with ♥")

        await ctx.send(embed=embed)

    @commands.command(hidden=True)
    @mido_utils.is_owner()
    async def reload(self, ctx, cog_name: str = None):
        # TODO: reload config inside ipc function so that all clusters reload the config
        self.bot.config = self.bot.get_config(self.bot.name, warn=False)

        responses = await self.bot.ipc.reload(target_cog=cog_name)

        e = mido_utils.Embed(ctx.bot, description="")
        for cluster_id, reloaded_cogs in responses:
            e.description += f"Cluster**#{cluster_id}**: Reloaded **{reloaded_cogs}** cog(s)\n"

        await ctx.send(embed=e)

    @commands.command(hidden=True)
    @mido_utils.is_owner()
    async def shutdown(self, ctx, *, cluster_id: int = None):
        if cluster_id is not None:
            await ctx.send(f"Shutting down cluster **{cluster_id}**...")
        else:
            await ctx.send("Shutting down all shards...")

        await self.bot.ipc.shutdown(cluster_id)

    @mido_utils.is_owner()
    @commands.command(name='setavatar', hidden=True)
    async def set_avatar(self, ctx, new_av: str = None):
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
                raise mido_utils.InvalidURL("Invalid URL!")

        await self.bot.user.edit(avatar=img_bytes)
        await ctx.send("Avatar has been successfully updated.")

    @commands.command()
    async def invite(self, ctx: mido_utils.Context):
        # TODO: add manage webhooks permission to invite links

        e = mido_utils.Embed(self.bot)
        e.title = f"Invite {self.bot.user} to your server:"
        e.description = f"[With Administrator Permission]" \
                        f"({mido_utils.links.invite_admin.format(self.bot.user.id)}) (Suggested)\n" \
                        f"[With Minimal Permissions]" \
                        f"({mido_utils.links.invite_minimal.format(self.bot.user.id)})\n" \
                        f"[With Selectable Permissions]" \
                        f"({mido_utils.links.invite_selectable.format(self.bot.user.id)})\n" \
                        f"[With No Permission]" \
                        f"({mido_utils.links.invite_none.format(self.bot.user.id)})"
        e.set_thumbnail(url=self.bot.user.avatar_url)

        await ctx.send(embed=e)

    @commands.command(aliases=['erasedata'])
    async def deletedata(self, ctx: mido_utils.Context):
        """Delete all of your data from me."""
        e = mido_utils.Embed(bot=self.bot,
                             description="Are you sure you'd like to erase all of your data?\n\n"
                                         "**This action is irreversible.**")

        msg = await ctx.send(embed=e)

        yes = await mido_utils.Embed.yes_no(bot=self.bot, author_id=ctx.author.id, msg=msg)
        if yes:
            await ctx.user_db.delete()

            await ctx.edit_custom(msg, "Your data has been successfully erased.")
        else:
            await ctx.edit_custom(msg, "Request declined.")

    @commands.command(aliases=['policy', 'privacypolicy'])
    async def privacy(self, ctx: mido_utils.Context):

        e = mido_utils.Embed(self.bot)
        e.title = f"{self.bot.user} Privacy Policy"
        e.description = f"By using this bot, or being in a server that this bot is also in, " \
                        f"you agree that you allow your messages and voice activity to be logged temporarily " \
                        f"for administration purposes. If you do not agree to this, " \
                        f"please kick me or leave the servers that I'm in."

        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Meta(bot))
