from typing import List

import discord
from discord.ext import commands, tasks

from midobot import MidoBot
from services.apis import NSFW_DAPIs, NekoAPI, RedditAPI
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import EmbedError, NotFoundError


class NSFW(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.api = NSFW_DAPIs(self.bot.http_session, self.bot.db)
        self.reddit = RedditAPI(self.bot.config['reddit_credentials'], self.bot.http_session, self.bot.db)
        self.neko = NekoAPI(session=self.bot.http_session, db=self.bot.db)

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

        self.fill_the_database.start()

    async def cog_command_error(self, ctx: MidoContext, error):
        if isinstance(error, NotFoundError):
            return await ctx.send_error("No results.")

    async def cog_check(self, ctx: MidoContext):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            raise EmbedError('This command can only be used in channels that are marked as NSFW.')

        return True

    def cog_unload(self):
        self.fill_the_database.cancel()

    async def send_nsfw_embed(self, ctx, image_url: str):
        e = MidoEmbed(bot=self.bot,
                      image_url=image_url,
                      # description=f"Image not working? [Report]({Resources.links.support_server})"
                      description=f"Image not working? [Click here.]({image_url})"
                      )
        e.set_footer(text=f"Shinobu NSFW API")
        await ctx.send(embed=e)

    async def _hentai(self, tags: str, limit=1, allow_video=False) -> List[str]:
        if not tags:
            return [(await self.reddit.get_from_the_db('hentai')).url for _ in range(limit)]
        else:
            return await self.api.get_bomb(tags, limit, allow_video)

    @tasks.loop(hours=1.0)
    async def fill_the_database(self):
        self.bot.logger.info('Checking hot posts from Reddit...')
        await self.reddit.fill_the_database()
        self.bot.logger.info('Checking hot posts from Reddit is done.')

    @commands.command(aliases=['boob'])
    async def boobs(self, ctx: MidoContext):
        """Get a random boob picture."""

        image = await self.reddit.get_from_the_db('boobs')
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command(aliases=['butt'])
    async def butts(self, ctx: MidoContext):
        """Get a random butt picture."""

        image = await self.reddit.get_from_the_db('butts')
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def porn(self, ctx: MidoContext):
        """Get a random porn content."""

        image = await self.reddit.get_from_the_db('general')
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def pussy(self, ctx: MidoContext):
        """Get a random pussy image."""

        image = await self.reddit.get_from_the_db('pussy')
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def asian(self, ctx: MidoContext):
        """Get a random asian porn content."""

        image = await self.reddit.get_from_the_db('asian')
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def gelbooru(self, ctx: MidoContext, *, tags: str = None):
        """Get a random image from Gelbooru.

        You must put '+' between different tags.
        `{0.prefix}hentaibomb yuri+group`"""

        image = await self.api.get('gelbooru', tags)
        await self.send_nsfw_embed(ctx, image[0])

    @commands.command()
    async def rule34(self, ctx: MidoContext, *, tags: str = None):
        """Get a random image from Rule34.

        You must put '+' between different tags.
        `{0.prefix}hentaibomb yuri+group`"""

        image = await self.api.get('rule34', tags)
        await self.send_nsfw_embed(ctx, image[0])

    @commands.command()
    async def danbooru(self, ctx: MidoContext, *, tags: str = None):
        """Get a random image from Danbooru.

        You must put '+' between different tags.
        `{0.prefix}hentaibomb yuri+group`"""

        image = await self.api.get('danbooru', tags)
        await self.send_nsfw_embed(ctx, image[0])

    @commands.command()
    async def lewdneko(self, ctx: MidoContext):
        """Get a random lewd neko image."""

        image = await self.neko.get_random_neko(nsfw=True)
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def hentai(self, ctx: MidoContext, *, tags: str = None):
        """Get a random hentai image.

        You must put '+' between different tags.
        `{0.prefix}hentaibomb yuri+group`"""
        image = await self._hentai(tags, limit=1)
        await self.send_nsfw_embed(ctx, image[0])

    @commands.command()
    async def hentaibomb(self, ctx: MidoContext, *, tags: str = None):
        """Get multiple hentai images.

        You must put '+' between different tags.
        `{0.prefix}hentaibomb yuri+group`"""
        image = await self._hentai(tags, limit=3, allow_video=True)

        await ctx.send(content="\n".join(im for im in image))


def setup(bot):
    bot.add_cog(NSFW(bot))
