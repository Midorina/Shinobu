from discord.ext import commands

from db.db_models import ModLogType, ModLog
from main import MidoBot
from services.converters import BetterMemberconverter
from services.time import MidoTime


class Moderation(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

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
                                         type=ModLogType.KICK,
                                         length=length)

        await ctx.send(f"`{modlog.id}` 🔨 "
                       f"User {target.mention} has been **banned** "
                       f"by {ctx.author.mention} for **{length.remaining_string}** "
                       f"with reason: `{reason}`")

    # TODO: moderation commands


def setup(bot):
    bot.add_cog(Moderation(bot))
