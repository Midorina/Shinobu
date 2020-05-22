from datetime import datetime

import discord
from discord.ext import commands

from db.models import MemberDB, UserDB
from main import MidoBot
from services import context, checks
from services.converters import BetterMemberconverter


class XP(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    async def get_xp_embed(self, user_or_member, db) -> discord.Embed:
        e = discord.Embed(color=self.bot.main_color,
                          title=str(user_or_member))

        # if in guild
        if isinstance(user_or_member, discord.Member):
            e.add_field(name='**Server Stats**',
                        value=f"**Level**: {db.level}\n"
                              f"**Total XP**: {db.total_xp}\n"
                              f"**Level Progress**: {db.progress}/{db.required_xp_to_level_up}\n"
                              f"**Server Rank**: #{await db.get_xp_rank()}")

            db = db.user

        e.add_field(name='**Global Stats**',
                    value=f"**Level**: {db.level}\n"
                          f"**Total XP**: {db.total_xp}\n"
                          f"**Level Progress**: {db.progress}/{db.required_xp_to_level_up}\n"
                          f"**Global Rank**: #{await db.get_xp_rank()}"
                    )

        e.set_thumbnail(url=user_or_member.avatar_url)
        e.timestamp = datetime.utcnow()

        return e

    def get_leaderboard_embed(self, top_10, title: str):
        e = discord.Embed(color=self.bot.main_color,
                          title=title)

        e.timestamp = datetime.utcnow()
        e.description = ""

        for i, user in enumerate(top_10, 1):
            user_obj = self.bot.get_user(user.id)

            # if its the #1 user
            if i == 1 and user_obj:
                e.set_thumbnail(url=user_obj.avatar_url)

            e.description += f"`#{i}` **{str(user_obj) if user_obj else user.id}**\n" \
                             f"Level: **{user.level}** | Total XP: **{user.total_xp}**\n\n"

        return e

    @staticmethod
    async def check_for_level_up(message: discord.Message, member_db: MemberDB, guild_name: str, added=0,
                                 added_globally=False):
        lvld_up_in_guild = member_db.progress < added
        lvld_up_globally = member_db.user.progress < added

        if not lvld_up_globally or not lvld_up_in_guild:
            return

        msg = f"🎉 **Congratulations {message.author.mention}!** 🎉\n"
        if lvld_up_in_guild:
            msg += f"You just have leveled up to **{member_db.level}** in {guild_name}!\n"

        # this is to prevent bugs
        if lvld_up_globally and added_globally:
            msg += f"You just have leveled up to **{member_db.user.level}** globally!"

        # if silent
        if member_db.guild.level_up_notifs_silenced:
            try:
                await message.author.send(msg)
            except discord.Forbidden:
                pass

        else:
            await message.channel.send(msg)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.is_ready() or message.author.bot:
            return False

        if message.guild is not None:
            member_db = await MemberDB.get_or_create(self.bot.db, message.guild.id, message.author.id)

            can_gain_xp = member_db.xp_date_status.end_date_has_passed
            can_gain_xp_global = member_db.user.xp_status.end_date_has_passed

            # if on cooldown
            if not can_gain_xp and not can_gain_xp_global:
                return

            if can_gain_xp:
                await member_db.add_xp(amount=3)

            if can_gain_xp_global:
                await member_db.user.add_xp(amount=3)

            await self.check_for_level_up(message, member_db, str(message.guild), added=3,
                                          added_globally=can_gain_xp_global)

    @commands.command(name="rank", aliases=['xp', 'level'])
    async def show_rank(self, ctx: context.Context, _member: BetterMemberconverter() = None):
        """See your or someone else's XP rank."""
        if _member:
            user = _member
            user_db = await MemberDB.get_or_create(ctx.db, ctx.guild.id, _member.id)
        else:
            user = ctx.author
            if ctx.guild:
                user_db = ctx.member_db
            else:
                user_db = ctx.user_db

        e = await self.get_xp_embed(user, user_db)

        await ctx.send(embed=e)

    @commands.command(name='leaderboard', aliases=['lb', 'xplb'])
    @commands.guild_only()
    async def show_leaderboard(self, ctx: context.Context):
        """See the XP leaderboard of the server."""
        top_10 = await ctx.guild_db.get_top_10()

        e = self.get_leaderboard_embed(top_10, title=f'XP Leaderboard of {ctx.guild}')

        await ctx.send(embed=e)

    @commands.command(name='gleaderboard', aliases=['globalleaderboard', 'glb', 'xpglb'])
    @commands.guild_only()
    async def show_global_leaderboard(self, ctx: context.Context):
        """See the global XP leaderboard."""
        top_10 = await ctx.user_db.get_top_10()

        e = self.get_leaderboard_embed(top_10, title='Global XP Leaderboard')

        await ctx.send(embed=e)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def silence_level_up_notifs(self, ctx: context.Context):
        """Silence level up notifications in this server.

        You need **Manage Guild** permission to use this command.
        """
        just_silenced = await ctx.guild_db.toggle_level_up_notifs()

        if just_silenced:
            await ctx.send("You've successfully silenced level up notifications in this server!")
        else:
            await ctx.send("You've successfully enabled level up notifications in this server!")

    @commands.command(name="addxp", hidden=True)
    @checks.owner_only()
    async def add_xp(self, ctx, member: BetterMemberconverter(), amount: int):
        member_db = await MemberDB.get_or_create(ctx.db, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.add_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="addgxp", hidden=True)
    @checks.owner_only()
    async def add_gxp(self, ctx, member: BetterMemberconverter(), amount: int):
        member_db = await UserDB.get_or_create(ctx.db, member.id)
        await member_db.add_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="removexp", aliases=['remxp'], hidden=True)
    @checks.owner_only()
    async def remove_xp(self, ctx, member: BetterMemberconverter(), amount: int):
        member_db = await MemberDB.get_or_create(ctx.db, guild_id=ctx.guild.id, member_id=member.id)
        await member_db.remove_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="removegxp", aliases=['remgxp'], hidden=True)
    @checks.owner_only()
    async def remove_gxp(self, ctx, member: BetterMemberconverter(), amount: int):
        member_db = await UserDB.get_or_create(ctx.db, member.id)
        await member_db.remove_xp(amount)
        await ctx.send("Success!")


def setup(bot):
    bot.add_cog(XP(bot))
