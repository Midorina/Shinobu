import typing

import discord
from discord.ext import commands, tasks

from db.db_models import ModLogType, ModLog
from main import MidoBot
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
                AND done IS NOT TRUE;""", [ModLogType.MUTE.value, ModLogType.BAN.value])

        for modlog in open_modlogs:
            # convert it to local obj
            modlog = ModLog(modlog, self.bot.db)

            # if its the time
            if modlog.time_status.end_date_has_passed:
                guild = self.bot.get_guild(modlog.guild_id)

                if modlog.type == ModLogType.BAN:
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
    def get_reason_string(reason = None):
        return f' with reason: `{reason}`' if reason else '.'

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, target: BetterMemberconverter(), *, reason: str = None):
        """Kicks a user."""

        await target.kick(reason=reason)
        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLogType.KICK)

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
        """Bans a user for a specified period of time or indefinitely."""

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
                                         type=ModLogType.BAN,
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
        """Unbans a banned user."""
        user_is_banned = await ctx.guild.fetch_ban(target)
        if not user_is_banned:
            return await ctx.send("That user isn't banned.")

        else:
            await ctx.guild.unban(target, reason=f"User unbanned by {ctx.author}"
                                                 f"{self.get_reason_string(reason)}")

            await ModLog.add_modlog(db_conn=ctx.db,
                                    guild_id=ctx.guild.id,
                                    user_id=target.id,
                                    type=ModLogType.UNBAN,
                                    executor_id=ctx.author.id,
                                    reason=reason)

            await ctx.send(f"User **{getattr(target, 'mention', target.id)}** "
                           f"has been **unbanned** "
                           f"by {ctx.author.mention}"
                           f"{self.get_reason_string(reason)}")

# TODO: mute, unmute, logs


def setup(bot):
    bot.add_cog(Moderation(bot))
