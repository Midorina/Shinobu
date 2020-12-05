import asyncio
import random
from typing import List

import discord
from discord.ext import commands, tasks

from midobot import MidoBot
from models.db import GuildDB
from services.apis import NSFW_DAPIs, NekoAPI, RedditAPI
from services.context import MidoContext
from services.embed import MidoEmbed
from services.exceptions import NotFoundError
from services.time_stuff import MidoTime


class NSFW(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.api = NSFW_DAPIs(self.bot.http_session, self.bot.db)
        self.reddit = RedditAPI(self.bot.config['reddit_credentials'], self.bot.http_session, self.bot.db)
        self.neko = NekoAPI(session=self.bot.http_session, db=self.bot.db)

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

        self.fill_the_database.start()

        self.active_auto_nsfw_services = list()
        self.bot.loop.create_task(self.start_auto_nsfw_services())

    async def start_auto_nsfw_services(self):
        auto_nsfw_guilds = await GuildDB.get_auto_nsfw_guilds(bot=self.bot)
        for guild in auto_nsfw_guilds:
            self.add_auto_nsfw_tasks(guild)

    def add_auto_nsfw_tasks(self, guild: GuildDB, type=None):
        if (type is None or type == 'hentai') and guild.auto_hentai_channel_id:
            task = self.bot.loop.create_task(self.auto_nsfw_loop(guild, type='hentai'), name=f'{guild.id}_hentai')
            self.active_auto_nsfw_services.append(task)

        if (type is None or type == 'porn') and guild.auto_porn_channel_id:
            task = self.bot.loop.create_task(self.auto_nsfw_loop(guild, type='porn'), name=f'{guild.id}_porn')
            self.active_auto_nsfw_services.append(task)

    def cancel_auto_nsfw_task(self, guild: GuildDB, type='hentai'):
        for task in self.active_auto_nsfw_services:  # find the guild
            if task.get_name() == f'{guild.id}_{type}':
                task.cancel()
                self.active_auto_nsfw_services.remove(task)

    async def auto_nsfw_loop(self, guild: GuildDB, type='hentai'):
        if type == 'hentai':
            db_channel_id = guild.auto_hentai_channel_id
            db_tags = guild.auto_hentai_tags
            db_interval = guild.auto_hentai_interval
        elif type == 'porn':
            db_channel_id = guild.auto_porn_channel_id
            db_tags = guild.auto_porn_tags
            db_interval = guild.auto_porn_interval
        else:
            raise Exception("Invalid NSFW type!")

        nsfw_channel = self.bot.get_channel(db_channel_id)

        fail_counter = 0
        while nsfw_channel and fail_counter < 10:  # if channel isn't found or set, code goes to the end
            tags = random.choice(db_tags) if db_tags else None

            try:
                if type == 'hentai':
                    image = (await self._hentai(tags=tags, limit=1))[0]
                elif type == 'porn':
                    image = (await self.reddit.get_reddit_post_from_db(self.bot,
                                                                       category='porn',
                                                                       tags=[tags] if tags else None,
                                                                       allow_gif='gif' in tags if tags else False)).url
                else:
                    raise Exception

                await self.send_nsfw_embed(nsfw_channel, image)

            except discord.Forbidden:
                nsfw_channel = None  # reset
                break

            except NotFoundError:
                e = MidoEmbed(bot=self.bot,
                              colour=discord.Colour.red(),
                              description=f"Could  not find anything with tag: `{tags}`")
                await nsfw_channel.send(embed=e)

                fail_counter += 1
                if fail_counter >= 10:
                    nsfw_channel = None
                    break

            await asyncio.sleep(db_interval)

        if not nsfw_channel:  # reset
            return await guild.set_auto_nsfw(type=type)

    async def cog_check(self, ctx: MidoContext):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            raise commands.NSFWChannelRequired(ctx.channel)

        return True

    def cog_unload(self):
        self.fill_the_database.cancel()

        for task in self.active_auto_nsfw_services:
            task.cancel()

        self.active_auto_nsfw_services = list()

    async def send_nsfw_embed(self, ctx_or_channel, image_url: str):
        e = MidoEmbed(bot=self.bot,
                      image_url=image_url,
                      description=f"Image not working? [Click here.]({image_url})"
                      )
        e.set_footer(text=f"{self.bot.name.title()} NSFW API")
        await ctx_or_channel.send(embed=e)

    async def _hentai(self, tags: str, limit=1, allow_video=False) -> List[str]:
        if not tags:
            return [(await self.reddit.get_reddit_post_from_db(self.bot, category='hentai')).url for _ in range(limit)]
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

        image = await self.reddit.get_reddit_post_from_db(ctx.bot, category='porn', tags=['boobs'])
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command(aliases=['butt', 'ass'])
    async def butts(self, ctx: MidoContext):
        """Get a random butt picture."""

        image = await self.reddit.get_reddit_post_from_db(ctx.bot, category='porn', tags=['butts'])
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def porn(self, ctx: MidoContext, *, tag: str = None):
        """Get a random porn content. A tag can be provided."""

        image = await self.reddit.get_reddit_post_from_db(ctx.bot, category='porn', tags=[tag] if tag else None)
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def pussy(self, ctx: MidoContext):
        """Get a random pussy image."""

        image = await self.reddit.get_reddit_post_from_db(ctx.bot, category='porn', tags=['pussy'])
        await self.send_nsfw_embed(ctx, image.url)

    @commands.command()
    async def asian(self, ctx: MidoContext):
        """Get a random asian porn content."""

        image = await self.reddit.get_reddit_post_from_db(ctx.bot, category='porn', tags=['asian'])
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
        `{0.prefix}hentaibomb yuri+group`

        **Danbooru doesn't allow more than 2 tags.**"""
        try:
            image = await self.api.get('danbooru', tags)
        except commands.TooManyArguments:
            raise commands.TooManyArguments("Danbooru doesn't allow more than 2 tags.")

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

    @commands.has_permissions(manage_messages=True)
    @commands.command()
    async def autohentai(self, ctx: MidoContext, interval: int = None, *, tags: str = None):
        """Have hentai automatically posted!

        Interval argument can be 3 seconds minimum.

        Put `+` between tags.
        Put `|` between tag groups. A random tag group will be chosen each time.
        (Tag argument can be left empty.)

        Don't type any argument to disable the autohentai service.

        Only 1 autohentai service can be active in a server.
        You need Manage Messages permission to use this command."""

        if not interval:
            if not ctx.guild_db.auto_hentai_channel_id:  # if already disabled
                raise commands.BadArgument("Autohentai is already disabled.")

            else:
                self.cancel_auto_nsfw_task(guild=ctx.guild_db, type='hentai')
                await ctx.guild_db.set_auto_nsfw(type='hentai')  # disable

                return await ctx.send_success("Autohentai service has successfully been disabled.")

        if interval < 3:
            raise commands.UserInputError("Interval can not be less than 3!")

        await ctx.guild_db.set_auto_nsfw(type='hentai',
                                         channel_id=ctx.channel.id,
                                         tags=tags.split('|') if tags else None,
                                         interval=interval)

        self.cancel_auto_nsfw_task(guild=ctx.guild_db, type='hentai')
        self.add_auto_nsfw_tasks(guild=ctx.guild_db, type='hentai')

        return await ctx.send_success(f"Success! I'll post hentai in this channel "
                                      f"every **{MidoTime.parse_seconds_to_str(interval)}** "
                                      f"with these tags: `{tags if tags else 'random'}`")

    @commands.has_permissions(manage_messages=True)
    @commands.command()
    async def autoporn(self, ctx: MidoContext, interval: int = None, *, tags: str = None):
        """Have porn automatically posted!

        Interval argument can be 3 seconds minimum.

        Put `|` between tag groups. A random tag group will be chosen each time.
        Please provide a single tag for each tag group (unlike `autohentai`)
        (Tag argument can be left empty.)

        Don't type any argument to disable the autoporn service.

        Only 1 autoporn service can be active in a server.
        You need Manage Messages permission to use this command."""

        if not interval:
            if not ctx.guild_db.auto_porn_channel_id:  # if already disabled
                raise commands.BadArgument("Autoporn is already disabled.")

            else:
                self.cancel_auto_nsfw_task(guild=ctx.guild_db, type='porn')
                await ctx.guild_db.set_auto_nsfw(type='porn')  # disable

                return await ctx.send_success("Autoporn service has successfully been disabled.")

        if interval < 3:
            raise commands.UserInputError("Interval can not be less than 3!")

        await ctx.guild_db.set_auto_nsfw(type='porn',
                                         channel_id=ctx.channel.id,
                                         tags=tags.split('|') if tags else None,
                                         interval=interval)

        self.cancel_auto_nsfw_task(guild=ctx.guild_db, type='porn')
        self.add_auto_nsfw_tasks(guild=ctx.guild_db, type='porn')

        return await ctx.send_success(f"Success! I'll post porn in this channel "
                                      f"every **{MidoTime.parse_seconds_to_str(interval)}** "
                                      f"with these tags: `{tags if tags else 'random'}`")


def setup(bot):
    bot.add_cog(NSFW(bot))
