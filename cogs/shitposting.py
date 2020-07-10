import random
from typing import Union

import discord
from discord.ext import commands

from main import MidoBot
from services.base_embed import BaseEmbed
from services.converters import MidoMemberConverter


class Shitposting(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command()
    async def penis(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = BaseEmbed(ctx.bot,
                          title=f"{user}'s Penis Size",
                          footer=False)

        embed.description = "8" + "=" * random.randrange(20) + "D"

        await ctx.send(embed=embed)

    @commands.command()
    async def howgay(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = BaseEmbed(ctx.bot, footer=False)

        embed.description = f"{user} is **{random.randrange(101)}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Shitposting(bot))
