from datetime import datetime

import discord
from discord.ext import commands

from db import db_funcs
from db.db_models import UserDB, GuildDB
from main import MidoBot
from services import context, checks


class XP(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    def get_xp_embed(self, user: discord.Member, user_db: UserDB) -> discord.Embed:
        level, current_xp, required_xp_to_lvl_up = self.calculate_user_xp_data(user_db.xp)

        e = discord.Embed(color=discord.Colour.blurple(),
                          title=str(user),
                          description=f"**Level**: {level}\n"
                                      f"**Total XP**: {user_db.xp}\n"
                                      f"**Level Progress**: {current_xp}/{required_xp_to_lvl_up}")

        e.set_thumbnail(url=user.avatar_url)
        e.set_footer(text=user.guild.name,
                     icon_url=user.guild.icon_url)
        e.timestamp = datetime.utcnow()

        return e

    @staticmethod
    def calculate_user_xp_data(user_xp: int):
        base_xp = 30
        total_xp = 0
        lvl = 1

        while True:
            required_xp_to_level_up = int(base_xp + base_xp / 3.0 * (lvl - 1))

            if required_xp_to_level_up + total_xp > user_xp:
                break

            total_xp += required_xp_to_level_up
            lvl += 1

        return lvl, user_xp - total_xp, required_xp_to_level_up

    async def check_for_level_up(self, message: discord.Message, user_db: UserDB, guild_db: GuildDB, added=0):
        level, current_xp, required_xp_to_lvl_up = self.calculate_user_xp_data(user_db.xp)

        # if leveled up
        if current_xp < added:
            # if silent
            if guild_db.level_up_notifs_silenced:
                return await message.author.send(f"🎉 **Congratulations {message.author.mention}!** "
                                                 f"You just have leveled up to **{level}**! 🎉")

            else:
                return await message.channel.send(f"🎉 **Congratulations {message.author.mention}!** "
                                                  f"You just have leveled up to **{level}**! 🎉")

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.bot.is_ready() or message.author.bot:
            return False

        if message.guild is not None:
            user_db = await db_funcs.get_user_db(self.bot.db, message.author.id)
            can_gain_xp, remaining = user_db.can_gain_xp_remaining

            # if on cooldown
            if not can_gain_xp:
                return

            await user_db.add_xp(amount=3)

    @commands.command(name="rank", aliases=['xp', 'level'])
    @commands.guild_only()
    async def show_rank(self, ctx: context.Context, _user: discord.Member = None):
        if _user:
            user = _user
            user_db = await db_funcs.get_user_db(ctx.db, _user.id)
        else:
            user = ctx.author
            user_db = ctx.author_db

        e = self.get_xp_embed(user, user_db)

        await ctx.send(embed=e)

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def silence_level_up_notifs(self, ctx: context.Context):
        just_silenced = await ctx.guild_db.toggle_level_up_notifs()

        if just_silenced:
            await ctx.send("You've successfully silenced level up notifications in this server!")
        else:
            await ctx.send("You've successfully enabled level up notifications in this server!")

    @commands.command(name="addxp")
    @checks.owner_only()
    async def add_xp(self, ctx, member: discord.Member, amount: int):
        member_db = await db_funcs.get_user_db(ctx.db, member.id)
        await member_db.add_xp(amount)
        await ctx.send("Success!")

    @commands.command(name="removexp", aliases=['remxp'])
    @checks.owner_only()
    async def remove_xp(self, ctx, member: discord.Member, amount: int):
        member_db = await db_funcs.get_user_db(ctx.db, member.id)
        await member_db.remove_xp(amount)
        await ctx.send("Success!")


def setup(bot):
    bot.add_cog(XP(bot))
