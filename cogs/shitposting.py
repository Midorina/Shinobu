from __future__ import annotations

import random
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

import mido_utils
from services import RedisCache

if TYPE_CHECKING:
    from shinobu import ShinobuBot
    from cogs.searches import Searches
    from cogs.nsfw import NSFW


class Shitposting(
    commands.Cog,
    description="RNG shitposting using `{ctx.prefix}8ball`, `{ctx.prefix}pp` and `{ctx.prefix}howgay`.\n"
                "Image filters using `{ctx.prefix}gay`, `{ctx.prefix}wasted`, `{ctx.prefix}triggered` and `{ctx.prefix}ytcomment`."):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.cache: RedisCache = RedisCache(self.bot)
        self.penis_cache = 1800  # half an hour
        self.gay_cache = 1800  # half an hour

    @discord.utils.cached_property
    def random_api(self) -> mido_utils.SomeRandomAPI:
        searches_cog: Searches = self.bot.get_cog('Searches')
        return searches_cog.some_random_api

    @discord.utils.cached_property
    def reddit_api(self) -> mido_utils.RedditAPI:
        nsfw_cog: NSFW = self.bot.get_cog('NSFW')
        return nsfw_cog.reddit

    @commands.hybrid_command(name='8ball')
    async def eight_ball(self, ctx: mido_utils.Context, *, question: str):
        """Ask a question to 8ball."""
        answer_index = random.randint(0, 19)

        e = mido_utils.Embed(bot=self.bot)
        e.set_author(icon_url=ctx.author.display_avatar.url, name=ctx.author)

        e.add_field(name='❓ Question', value=question, inline=False)
        e.add_field(name='🎱 8ball', value=mido_utils.strings.eight_ball_responses[answer_index],
                    inline=False)

        if answer_index < 10:
            e.colour = 0x008000
        elif answer_index < 15:
            e.colour = 0xffd700
        else:
            e.colour = 0xff0000

        await ctx.send(embed=e)

    @commands.hybrid_command(aliases=['pp', 'sikboyu'])
    async def penis(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Learn the size of penis of someone."""
        user = target or ctx.author

        # decide prefix
        prefix = "8"
        if user.id == 340918740134658052:  # taylan
            prefix = "o"

        # decide length
        key = str(user.id) + "_pen"
        if await self.cache.get(key):
            length = int(await self.cache.get(key))
        else:
            length = random.randrange(25)
            await self.cache.set(key, length, self.penis_cache)

        # prepare embed
        embed = mido_utils.Embed(ctx.bot,
                                 title=f"{user.display_name if isinstance(user, discord.Member) else user}'s Penis Size")
        embed.description = prefix + "=" * length + "D"

        await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def howgay(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Learn how gay someone is."""
        user = target or ctx.author

        # decide how gay
        key = str(user.id) + "_gay"
        if await self.cache.get(key):
            how_gay = int(await self.cache.get(key))
        else:
            how_gay = random.randrange(101)
            await self.cache.set(key, how_gay, self.gay_cache)

        # prepare embed
        embed = mido_utils.Embed(ctx.bot)
        embed.description = f"{user.display_name if isinstance(user, discord.Member) else user} is **{how_gay}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)

    @commands.hybrid_command()
    async def gay(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Place a pride flag on someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.display_avatar.replace(static_format='png')),
            _type="gay")

        await ctx.send_simple_image(url)

    @commands.hybrid_command()
    async def wasted(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Place a wasted screen on someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.display_avatar.replace(static_format='png')),
            _type="wasted")

        await ctx.send_simple_image(url)

    @commands.hybrid_command()
    async def triggered(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """See triggered version of someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.display_avatar.replace(static_format='png')),
            _type="triggered")

        await ctx.send_simple_image(url)

    @commands.cooldown(rate=1, per=3, type=commands.BucketType.guild)
    @commands.hybrid_command()
    async def dadjoke(self, ctx: mido_utils.Context):
        """Get a random dad joke."""
        await ctx.send_success(await self.random_api.get_joke())

    @commands.hybrid_command()
    async def meme(self, ctx: mido_utils.Context):
        """Get a random meme."""
        image = (await self.reddit_api.get_reddit_post_from_db(ctx.bot, category='meme'))[0]
        await ctx.send_simple_image(image.url)

    @commands.guild_only()
    @commands.hybrid_command(aliases=['youtubecomment'])
    async def ytcomment(self, ctx: mido_utils.Context, target: mido_utils.MemberConverter = None, *, comment: str = ''):
        """Generate a YouTube comment."""
        if not target and not comment:
            raise commands.BadArgument("You should at least provide a comment to be shown in the image.")

        # if only comment is passed
        if isinstance(target, str):
            comment = f"{target} {comment}"
            target = None

        user = target or ctx.author

        await ctx.send_simple_image(
            url=await self.random_api.youtube_comment(
                avatar_url=str(user.display_avatar.replace(static_format='png')),
                username=user.display_name,
                comment=comment)
        )

    @commands.hybrid_command()
    async def say(self, ctx: mido_utils.Context, *, message: str):
        """Make me say something."""
        # commands.clean_content is not used, because the message will be shown in an embed.
        await ctx.send_success(message)


async def setup(bot: ShinobuBot):
    await bot.add_cog(Shitposting(bot))
