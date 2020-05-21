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
    async def kick(self, ctx, target: BetterMemberconverter(), reason: str = None):
        """Kicks a user."""

        await target.kick(reason=reason)
        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLogType.KICK)

        await ctx.send(f"`{modlog.id}` 👢 "
                       f"User {target.mention} has been **kicked** "
                       f"by {ctx.author.mention} with reason: `{reason}`")

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, target: BetterMemberconverter(), length: MidoTime = None, reason: str = None):
        """Bans a user for a specified period of time or indefinitely."""
        # await target.ban(reason=reason,
        #                  delete_message_days=1)
        print(length.end_date)
        modlog = await ModLog.add_modlog(ctx.db,
                                         guild_id=ctx.guild.id,
                                         user_id=target.id,
                                         reason=reason,
                                         executor_id=ctx.author.id,
                                         type=ModLogType.BAN,
                                         length=length_or_reason)

        await ctx.send(f"`{modlog.id}` 🔨 "
                       f"User {target.mention} has been **banned** "
                       f"by {ctx.author.mention} for **{length.remaining_string}** "
                       f"with reason: `{reason}`")

    # TODO: moderation commands


def setup(bot):
    bot.add_cog(Moderation(bot))
