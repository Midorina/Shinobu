import random
from typing import Union

import discord
from discord.ext import commands

from midobot import MidoBot
from services.apis import SomeRandomAPI
from services.context import MidoContext
from services.converters import MidoMemberConverter
from services.embed import MidoEmbed
from services.resources import Resources


class Shitposting(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    def get_random_api(self) -> SomeRandomAPI:
        return self.bot.get_cog('Searches').some_random_api

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
    async def howgay(self, ctx: MidoContext, *, target: Union[MidoMemberConverter, str] = None):
        """Learn how gay someone is."""
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = MidoEmbed(ctx.bot)

        embed.description = f"{user} is **{random.randrange(101)}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)

    @commands.command()
    async def gay(self, ctx: MidoContext, *, target: Union[MidoMemberConverter, str] = None):
        """Place a pride flag on someone's avatar."""
        user = target or ctx.author

        url = await self.get_random_api().wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="gay")

        await ctx.send_simple_image(url)

    @commands.command()
    async def wasted(self, ctx: MidoContext, *, target: Union[MidoMemberConverter, str] = None):
        """Place a wasted screen on someone's avatar."""
        user = target or ctx.author

        url = await self.get_random_api().wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="wasted")

        await ctx.send_simple_image(url)

    @commands.command()
    async def triggered(self, ctx: MidoContext, *, target: Union[MidoMemberConverter, str] = None):
        """See triggered version of someone's avatar."""
        user = target or ctx.author

        url = await self.get_random_api().wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="triggered")

        await ctx.send_simple_image(url)

    @commands.command()
    async def joke(self, ctx: MidoContext):
        """Get a random joke."""
        await ctx.send_success(await self.get_random_api().get_joke())

    @commands.command()
    async def meme(self, ctx: MidoContext):
        """Get a random meme."""
        await ctx.send_simple_image(await self.get_random_api().get_meme())

    @commands.command()
    async def youtube(self, ctx: MidoContext, target: Union[MidoMemberConverter, str] = None, *, comment: str = ''):
        # if only comment is passed
        if isinstance(target, str):
            comment = f"{target} {comment}"
            target = None

        user = target or ctx.author

        await ctx.send_simple_image(
            url=await self.get_random_api().youtube_comment(
                avatar_url=str(user.avatar_url_as(static_format='png')),
                username=str(user),
                comment=comment)
        )


def setup(bot):
    bot.add_cog(Shitposting(bot))
