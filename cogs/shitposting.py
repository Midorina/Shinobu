import random
from typing import Union

import discord
from discord.ext import commands

import mido_utils
from shinobu import ShinobuBot


class Shitposting(
    commands.Cog,
    description="RNG shitposting using `{ctx.prefix}8ball`, `{ctx.prefix}pp` and `{ctx.prefix}howgay`.\n"
                "Image filters using `{ctx.prefix}gay`, `{ctx.prefix}wasted`, `{ctx.prefix}triggered` and `{ctx.prefix}ytcomment`."):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

    @discord.utils.cached_property
    def random_api(self) -> mido_utils.SomeRandomAPI:
        return self.bot.get_cog('Searches').some_random_api

    @discord.utils.cached_property
    def reddit_api(self) -> mido_utils.RedditAPI:
        return self.bot.get_cog('NSFW').reddit

    @commands.command(name='8ball')
    async def eight_ball(self, ctx: mido_utils.Context, *, question: str):
        """Ask a question to 8ball."""
        answer_index = random.randint(0, 19)

        e = mido_utils.Embed(bot=self.bot)
        e.set_author(icon_url=ctx.author.avatar_url, name=ctx.author)

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

    @commands.command(aliases=['pp'])
    async def penis(self, ctx, *, target: Union[mido_utils.MemberConverter, str] = None):
        """Learn the size of penis of someone."""
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = mido_utils.Embed(ctx.bot,
                                 title=f"{user}'s Penis Size")

        embed.description = "8" + "=" * random.randrange(20) + "D"

        await ctx.send(embed=embed)

    @commands.command()
    async def howgay(self, ctx: mido_utils.Context, *, target: Union[mido_utils.MemberConverter, str] = None):
        """Learn how gay someone is."""
        user = target or ctx.author
        if isinstance(user, discord.Member):
            user = user.display_name

        embed = mido_utils.Embed(ctx.bot)

        embed.description = f"{user} is **{random.randrange(101)}% gay 🏳️‍🌈**"

        await ctx.send(embed=embed)

    @commands.command()
    async def gay(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Place a pride flag on someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="gay")

        await ctx.send_simple_image(url)

    @commands.command()
    async def wasted(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """Place a wasted screen on someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="wasted")

        await ctx.send_simple_image(url)

    @commands.command()
    async def triggered(self, ctx: mido_utils.Context, *, target: mido_utils.MemberConverter = None):
        """See triggered version of someone's avatar."""
        user = target or ctx.author

        url = await self.random_api.wasted_gay_or_triggered(
            avatar_url=str(user.avatar_url_as(static_format='png')),
            _type="triggered")

        await ctx.send_simple_image(url)

    @commands.cooldown(rate=1, per=3, type=commands.BucketType.guild)
    @commands.command()
    async def dadjoke(self, ctx: mido_utils.Context):
        """Get a random dad joke."""
        await ctx.send_success(await self.random_api.get_joke())

    @commands.command()
    async def meme(self, ctx: mido_utils.Context):
        """Get a random meme."""
        image = (await self.reddit_api.get_reddit_post_from_db(ctx.bot, category='meme'))[0]
        await ctx.send_simple_image(image.url)

    @commands.guild_only()
    @commands.command(aliases=['youtubecomment'])
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
                avatar_url=str(user.avatar_url_as(static_format='png')),
                username=user.display_name,
                comment=comment)
        )

    @commands.command()
    async def say(self, ctx: mido_utils.Context, *, message: str):
        """Make me say something."""
        # commands.clean_content is not used, because the message will be shown in an embed.
        await ctx.send_success(message)


def setup(bot):
    bot.add_cog(Shitposting(bot))
