import random
from typing import Union

import discord
from discord.ext import commands

from main import MidoBot
from services.converters import MidoMemberConverter
from services.embed import MidoEmbed


class Shitposting(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command()
    async def penis(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = MidoEmbed(ctx.bot,
                          title=f"{user}'s Penis Size")

        embed.description = "8" + "=" * random.randrange(20) + "D"

        await ctx.send(embed=embed)

    @commands.command()
    async def howgay(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = MidoEmbed(ctx.bot)

        embed.description = f"{user} is **{random.randrange(101)}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Shitposting(bot))
