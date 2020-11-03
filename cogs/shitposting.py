import random
from typing import Union

import discord
from discord.ext import commands

from midobot import MidoBot
from services.context import MidoContext
from services.converters import MidoMemberConverter
from services.embed import MidoEmbed
from services.resources import Resources


class Shitposting(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.command(name='8ball')
    async def _8ball(self, ctx: MidoContext, *, question: str):
        """Ask a question to 8ball."""
        answer_index = random.randint(0, 19)

        e = MidoEmbed(bot=self.bot)
        e.set_author(icon_url=ctx.author.avatar_url, name=ctx.author)

        e.add_field(name='❓ Question', value=question, inline=False)
        e.add_field(name='🎱 8ball', value=Resources.strings.eight_ball_responses[answer_index], inline=False)

        if answer_index < 10:
            e.colour = 0x008000
        elif answer_index < 15:
            e.colour = 0xffd700
        else:
            e.colour = 0xff0000

        await ctx.send(embed=e)

    @commands.command()
    async def penis(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        """Learn the size of penis of someone."""
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = MidoEmbed(ctx.bot,
                          title=f"{user}'s Penis Size")

        embed.description = "8" + "=" * random.randrange(20) + "D"

        await ctx.send(embed=embed)

    @commands.command()
    async def howgay(self, ctx, *, target: Union[MidoMemberConverter, str] = None):
        """Learn how gay someone is."""
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = MidoEmbed(ctx.bot)

        embed.description = f"{user} is **{random.randrange(101)}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Shitposting(bot))
