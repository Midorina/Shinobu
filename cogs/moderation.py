import typing

import discord
from discord.ext import commands, tasks

from db.db_models import ModLog
from main import MidoBot
from services import base_embed, menu_stuff
from services.context import Context
from services.converters import BetterMemberconverter
from services.time import MidoTime


class Moderation(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.check_modlogs.start()

    @tasks.loop(seconds=30.0)
    async def check_modlogs(self):
        open_modlogs = await self.bot.db.fetch(
            """
            SELECT 
                *
            FROM 
                modlogs 
            WHERE 
                length_in_seconds IS NOT NULL 
                AND type = ANY($1) 
                AND done IS NOT TRUE;""", [ModLog.Type.MUTE.value, ModLog.Type.BAN.value])

        for modlog in open_modlogs:
            # convert it to local obj
            modlog = ModLog(modlog, self.bot.db)

            # if its the time
            if modlog.time_status.end_date_has_passed:
                guild = self.bot.get_guild(modlog.guild_id)

                if modlog.type == ModLog.Type.BAN:
                    member = discord.Object(id=modlog.user_id)
                    await guild.unban(member, reason='ModLog time has expired. (Auto-Unban)')
                    await modlog.complete()

                # TODO: add mute

    def cog_unload(self):
        self.check_modlogs.cancel()

    @check_modlogs.before_loop
    async def before_modlog_checks(self):
        await self.bot.wait_until_ready()

    @staticmethod
    def get_reason_string(reason=None):
        return f' with reason: `{reason}`' if reason else '.'

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, target: BetterMemberconverter(), *, reason: str = None):
        """Kicks a user.

        You need the Kick Members permission to use this command.
        """

        await target.kick(reason=reason)
        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLog.Type.KICK)

        await ctx.send(f"`{modlog.id}` 👢 "
                       f"User {getattr(target, 'mention', target.id)} has been **kicked** "
                       f"by {ctx.author.mention}"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self,
                  ctx: Context,
                  target: BetterMemberconverter(),
                  length_or_reason: typing.Union[MidoTime, str] = None,
                  *, reason: str = None):
        """Bans a user for a specified period of time or indefinitely.

        **Examples:**
            `{0.prefix}ban @Mido` (bans permanently)
            `{0.prefix}ban @Mido toxic` (bans permanently with a reason)
            `{0.prefix}ban @Mido 30m` (bans for 30 minutes)
            `{0.prefix}ban @Mido 3d toxic` (bans for 3 days with reason)

        **Available time length letters:**
            `s` -> seconds
            `m` -> minutes
            `h` -> hours
            `d` -> days
            `w` -> weeks
            `mo` -> months
        """

        # if only reason is passed
        if isinstance(length_or_reason, str) and reason:
            reason = f"{length_or_reason} {reason}"
            length_or_reason = None

        await target.ban(reason=reason,
                         delete_message_days=1)

        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLog.Type.BAN,
                                         length=length_or_reason)

        await ctx.send(f"`{modlog.id}` 🔨 "
                       f"User **{getattr(target, 'mention', target.id)}** "
                       f"has been **banned** "
                       f"by {ctx.author.mention} "
                       f"for **{getattr(length_or_reason, 'remaining_string', 'permanently')}**"
                       f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self,
                    ctx: Context,
                    target: BetterMemberconverter(),
                    *, reason: str = None):
        """Unbans a banned user.

        You need Ban Members permission to use this command.
        """

        user_is_banned = await ctx.guild.fetch_ban(target)
        if not user_is_banned:
            return await ctx.send("That user isn't banned.")

        else:
            await ctx.guild.unban(target, reason=f"User unbanned by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

            await ModLog.add_modlog(db_conn=ctx.db,
                                    guild_id=ctx.guild.id,
                                    user_id=target.id,
                                    type=ModLog.Type.UNBAN,
                                    executor_id=ctx.author.id,
                                    reason=reason)

            await ctx.send(f"User **{getattr(target, 'mention', target.id)}** "
                           f"has been **unbanned** "
                           f"by {ctx.author.mention}"
                           f"{self.get_reason_string(reason)}")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True, kick_members=True)
    async def logs(self,
                   ctx: Context,
                   target: BetterMemberconverter()):
        """See the logs of a user.

        You need Kick Members and Ban Members permissions to use this command.
        """

        logs = await ModLog.get_logs(ctx.db, ctx.guild.id, target.id)
        if not logs:
            return await ctx.send("No logs have been found for that user.")

        e = base_embed.BaseEmbed(self.bot)
        e.set_author(icon_url=getattr(target, 'avatar_url', None),
                     name=f"Logs of {target}")
        e.set_footer(text=f"{len(logs)} Logs")

        log_blocks = []
        for log in logs:
            log_description = f"**Case ID:** `{log.id}`\n" \
                              f"**Action:** {log.type.name.title()}\n"

            if log.length_string:
                log_description += f'**Length:** {log.length_string}\n'

            if log.reason:
                log_description += f"**Reason:** {log.reason}\n"

            log_description += f"**Executor:** <@{log.executor_id}>"

            log_blocks.append(log_description)

        await menu_stuff.paginate(self.bot, ctx, blocks=log_blocks, embed=e, extra_sep='\n')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def clearlogs(self,
                        ctx: Context,
                        target: BetterMemberconverter()):
        """Clears the logs of a user.

        You need to have the Administrator permission to use this command.
        """

        msg = await ctx.send(f"Are you sure you'd like to reset the logs of **{target}**?")
        yes = await menu_stuff.yes_no(self.bot, ctx.author.id, msg)

        if not yes:
            return await msg.edit(content="Request has been declined.")

        else:
            await ModLog.hide_logs(ctx.db, ctx.guild.id, target.id)

            return await msg.edit(content=f"Logs of **{target}** has been successfully deleted.")

# TODO: mute, unmute


def setup(bot):
    bot.add_cog(Moderation(bot))
