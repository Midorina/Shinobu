import asyncio
import random
from typing import Dict, List

import discord
from discord.ext import commands, tasks

import mido_utils
from midobot import MidoBot
from models.db import CachedImage, GuildNSFWDB, NSFWImage


class NSFW(commands.Cog,
           description='Get quality NSFW images. '
                       'Check out `{ctx.prefix}autohentai` to have them posted automatically.'):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.api = mido_utils.NSFW_DAPIs(self.bot.http_session, self.bot)
        self.reddit = mido_utils.RedditAPI(self.bot.config['reddit_credentials'], self.bot.http_session, self.bot.db)
        self.neko = mido_utils.NekoAPI(session=self.bot.http_session, db=self.bot.db)

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

        self.fill_the_database.start()

        self.active_auto_nsfw_services = list()
        self.start_auto_nsfw_task = self.bot.loop.create_task(self.start_auto_nsfw_services())
        self.start_checking_urls_task = self.bot.loop.create_task(self.start_checking_urls_in_db())

        # tag: image list
        self.hentai_cache: Dict[str, List[NSFWImage]] = dict()
        self.porn_cache: Dict[str, List[NSFWImage]] = dict()

    def get_nsfw_cache(self, nsfw_type: NSFWImage.Type):
        if nsfw_type is NSFWImage.Type.hentai:
            return self.hentai_cache
        elif nsfw_type is NSFWImage.Type.porn:
            return self.porn_cache
        else:
            raise mido_utils.UnknownNSFWType

    async def get_nsfw_image(self, nsfw_type: NSFWImage.Type, tags: str, limit=1, allow_video=False,
                             guild_id: int = None) -> List[NSFWImage]:
        tag_list = tags.replace(' ', '_').lower().split('+') if tags else []
        blacklisted_tags = await self.api.get_blacklisted_tags(guild_id)

        if not allow_video and tags:
            allow_video = 'video' in tags

        ret = []

        cache = self.get_nsfw_cache(nsfw_type)

        i = 0
        while len(ret) < limit:
            try:
                pulled = cache[tags].pop(0)

                add = True
                # check for blacklisted tags
                for tag in pulled.tags:
                    if tag in blacklisted_tags:
                        # image is blacklisted
                        add = False
                        break

                if add is True:
                    # make additional tag check.
                    # if the pulled image does not contain the tags we want,
                    # it was most likely added by a server with blacklisted tags
                    for tag in tag_list:
                        if tag not in pulled.tags and tag not in blacklisted_tags:
                            # image doesnt contain a tag we want
                            add = False
                            break

                if add is True:
                    ret.append(pulled)
                else:
                    cache[tags].append(pulled)
                    i += 1

                    # if we scanned the whole cache, raise IndexError to get more images
                    if i >= len(cache[tags]):
                        raise IndexError

            except (KeyError, IndexError):
                # if porn is requested or tags are not provided, pull from db
                if nsfw_type is NSFWImage.Type.porn or not tags:
                    new_images = await self.reddit.get_reddit_post_from_db(
                        self.bot,
                        category=nsfw_type.name,
                        tags=[tags] if tags else None,
                        limit=500,
                        allow_gif=True)
                else:
                    new_images = await self.api.get_bomb(tags=tags,
                                                         limit=500,
                                                         allow_video=allow_video,
                                                         guild_id=guild_id)

                if tags in cache.keys():
                    cache[tags].extend(new_images)
                else:
                    cache[tags] = new_images

                ret.append(cache[tags].pop(0))

        return ret

    async def start_checking_urls_in_db(self):
        await self.bot.wait_until_ready()

        while True:
            images = await CachedImage.get_oldest_checked_images(self.bot, limit=100)
            for image in images:
                time = mido_utils.Time()
                try:
                    if await image.url_is_working() is False:
                        await image.delete()
                except Exception as e:
                    await self.bot.get_cog('ErrorHandling').on_error(str(e))
                finally:
                    self.bot.logger.debug(f"Checking 1 image took:\t\t{time.passed_seconds_in_float_formatted}")
                    await asyncio.sleep(1.0)
            await asyncio.sleep(5.0)

    async def start_auto_nsfw_services(self):
        await self.bot.wait_until_ready()

        time = mido_utils.Time()
        auto_nsfw_guilds = await GuildNSFWDB.get_auto_nsfw_guilds(bot=self.bot)
        for guild in auto_nsfw_guilds:
            self.add_auto_nsfw_tasks(guild)
            await asyncio.sleep(0.33)

        self.bot.logger.debug("Adding auto nsfw services took:\t" + time.passed_seconds_in_float_formatted)

    def add_auto_nsfw_tasks(self, nsfw_db: GuildNSFWDB, nsfw_type: NSFWImage.Type = None):
        for base_nsfw_type in NSFWImage.Type:
            db_channel_id, db_tags, db_interval = nsfw_db.get_auto_nsfw_properties(base_nsfw_type)

            if (nsfw_type is None or nsfw_type is base_nsfw_type) and db_channel_id:
                task = self.bot.loop.create_task(self.auto_nsfw_loop(nsfw_db, nsfw_type=base_nsfw_type),
                                                 name=f'{nsfw_db.id}_{base_nsfw_type.name}')
                self.active_auto_nsfw_services.append(task)

    def cancel_auto_nsfw_task(self, nsfw_db: GuildNSFWDB, nsfw_type: NSFWImage.Type):
        for task in self.active_auto_nsfw_services:  # find the guild
            if task.get_name() == f'{nsfw_db.id}_{nsfw_type.name}':
                task.cancel()
                self.active_auto_nsfw_services.remove(task)

    async def auto_nsfw_loop(self, guild: GuildNSFWDB, nsfw_type: NSFWImage.Type):

        db_channel_id, db_tags, db_interval = guild.get_auto_nsfw_properties(nsfw_type)

        nsfw_channel = self.bot.get_channel(db_channel_id)

        fail_counter = 0
        while nsfw_channel and fail_counter < 5:  # if channel isn't found or set, code goes to the end
            time = mido_utils.Time()
            self.bot.logger.debug(
                f"CACHE SIZE: {sum(len(x) for x in self.porn_cache.values()) + sum(len(x) for x in self.hentai_cache.values())}")

            tags = random.choice(db_tags) if db_tags else None
            try:
                image = (await self.get_nsfw_image(nsfw_type=nsfw_type, tags=tags, limit=1, guild_id=guild.id))[0]
            except mido_utils.NotFoundError:
                e = mido_utils.Embed(bot=self.bot,
                                     colour=discord.Colour.red(),
                                     description=f"Could  not find anything with tag: `{tags}`")
                await nsfw_channel.send(embed=e)

                fail_counter += 1
                continue

            try:
                await self.bot.send_as_webhook(nsfw_channel, **image.get_send_kwargs(self.bot))
            except discord.Forbidden:
                nsfw_channel = None  # reset
                break

            self.bot.logger.debug(f"Sending auto-{nsfw_type.name} took:\t\t{time.passed_seconds_in_float_formatted}")

            await asyncio.sleep(db_interval)

        if fail_counter >= 5 and nsfw_channel:
            e = mido_utils.Embed(bot=self.bot,
                                 colour=discord.Colour.red(),
                                 description=f"Too many failed attempts. Disabling auto-{nsfw_type.name}...")
            await nsfw_channel.send(embed=e)

        return await guild.set_auto_nsfw(nsfw_type=nsfw_type)  # reset

    @tasks.loop(hours=1.0)
    async def fill_the_database(self):
        await self.bot.wait_until_ready()

        time = mido_utils.Time()
        await self.reddit.fill_the_database()
        self.bot.logger.debug('Checking hot posts from Reddit took:\t' + time.passed_seconds_in_float_formatted)

    @fill_the_database.error
    async def task_error(self, error):
        await self.bot.get_cog('ErrorHandling').on_error(error)

    async def cog_check(self, ctx: mido_utils.Context):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            raise commands.NSFWChannelRequired(ctx.channel)

        return True

    def cog_unload(self):
        self.start_auto_nsfw_task.cancel()
        self.start_checking_urls_task.cancel()
        self.fill_the_database.cancel()

        for task in self.active_auto_nsfw_services:
            task.cancel()

        self.active_auto_nsfw_services = list()

    @commands.command()
    async def porn(self, ctx: mido_utils.Context, *, tag: str = None):
        """Get a random porn content. A tag can be provided."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags=tag, limit=1,
                                           guild_id=getattr(ctx.guild, 'id', None)))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(aliases=['boob'])
    async def boobs(self, ctx: mido_utils.Context):
        """Get a random boob picture."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags='boobs', limit=1,
                                           guild_id=getattr(ctx.guild, 'id', None)))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(aliases=['butt', 'ass'])
    async def butts(self, ctx: mido_utils.Context):
        """Get a random butt picture."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags='butts', limit=1,
                                           guild_id=getattr(ctx.guild, 'id', None)))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def pussy(self, ctx: mido_utils.Context):
        """Get a random pussy image."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags='pussy', limit=1,
                                           guild_id=getattr(ctx.guild, 'id', None)))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def asian(self, ctx: mido_utils.Context):
        """Get a random asian porn content."""

        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags='asian', limit=1,
                                           guild_id=getattr(ctx.guild, 'id', None)))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def gelbooru(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Gelbooru.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""

        image = (
            await self.api.get('gelbooru', tags, guild_id=ctx.guild.id if ctx.guild else None)
        )[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def rule34(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Rule34.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""

        image = (await self.api.get('rule34', tags, guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(aliases=['sankakucomplex'])
    async def sankaku(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Rule34.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""

        image = (await self.api.get('sankaku_complex', tags, guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def danbooru(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Danbooru.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`

        **Danbooru doesn't allow more than 2 tags.**"""
        image = (await self.api.get('danbooru', tags, guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(name='lewdneko')
    async def lewd_neko(self, ctx: mido_utils.Context):
        """Get a random lewd neko image."""

        image = await self.neko.get_random_neko(nsfw=True)
        image = NSFWImage(image.url, tags='neko', api_name='Nekos.Life')
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()
    async def hentai(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random hentai image.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""
        image = \
            (await self.get_nsfw_image(NSFWImage.Type.hentai, tags, limit=1, guild_id=getattr(ctx.guild, 'id', None)))[
                0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(name='hentaibomb')
    async def hentai_bomb(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get multiple hentai images.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""
        images = await self.get_nsfw_image(NSFWImage.Type.hentai, tags, limit=3, allow_video=True,
                                           guild_id=getattr(ctx.guild, 'id', None))

        await ctx.send(content="\n".join(im.url for im in images))

    async def base_auto_nsfw_cmd(self,
                                 ctx: mido_utils.Context,
                                 nsfw_type: NSFWImage.Type,
                                 interval: mido_utils.Int32() = None,
                                 tags: str = None):
        nsfw_db = await GuildNSFWDB.get_or_create(ctx.bot, ctx.guild.id)

        db_channel_id, db_tags, db_interval = nsfw_db.get_auto_nsfw_properties(nsfw_type)

        if not interval:
            if not db_channel_id:  # if already disabled
                raise commands.BadArgument(f"Auto-{nsfw_type.name} is already disabled.")

            else:
                self.cancel_auto_nsfw_task(nsfw_db=nsfw_db, nsfw_type=nsfw_type)
                await nsfw_db.set_auto_nsfw(nsfw_type=nsfw_type, channel_id=None)  # disable

                return await ctx.send_success(f"Auto-{nsfw_type.name} service has successfully been disabled.")

        if interval < 3:
            raise commands.UserInputError("Interval can not be less than 3!")

        await nsfw_db.set_auto_nsfw(nsfw_type=nsfw_type,
                                    channel_id=ctx.channel.id,
                                    tags=tags.split('|') if tags else None,
                                    interval=interval)

        self.cancel_auto_nsfw_task(nsfw_db=nsfw_db, nsfw_type=nsfw_type)
        self.add_auto_nsfw_tasks(nsfw_db=nsfw_db, nsfw_type=nsfw_type)

        return await ctx.send_success(f"Success! I'll automatically post {nsfw_type.name} in this channel "
                                      f"every **{mido_utils.Time.parse_seconds_to_str(interval)}** "
                                      f"with these tags: `{tags if tags else 'random'}`")

    @commands.has_permissions(manage_messages=True)
    @commands.command(name='autohentai')
    @commands.bot_has_permissions(manage_webhooks=True)
    async def auto_hentai(self, ctx: mido_utils.Context, interval: mido_utils.Int32() = None, *, tags: str = None):
        """Have hentai automatically posted!

        Interval argument can be 3 seconds minimum.

        Put `+` between tags.
        Put `|` between tag groups. A random tag group will be chosen each time.
        (Tag argument can be left empty.)

        Don't type any argument to disable the autohentai service.

        Only 1 autohentai service can be active in a server.
        You need Manage Messages permission to use this command."""

        await self.base_auto_nsfw_cmd(ctx, NSFWImage.Type.hentai, interval, tags)

    @commands.has_permissions(manage_messages=True)
    @commands.command(name='autoporn')
    @commands.bot_has_permissions(manage_webhooks=True)
    async def auto_porn(self, ctx: mido_utils.Context, interval: mido_utils.Int32() = None, *, tags: str = None):
        """Have porn automatically posted!

        Interval argument can be 3 seconds minimum.

        Put `|` between tag groups. A random tag group will be chosen each time.
        Please provide a single tag for each tag group (unlike `autohentai`)
        (Tag argument can be left empty.)

        Don't type any argument to disable the autoporn service.

        Only 1 autoporn service can be active in a server.
        You need Manage Messages permission to use this command."""

        await self.base_auto_nsfw_cmd(ctx, NSFWImage.Type.porn, interval, tags)

    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.command(name="tagblacklist")
    async def blacklist_tag(self, ctx: mido_utils.Context, *, tag: str = None):
        """See the blacklisted tags or blacklist a tag. Provide a tag to blacklist it.
        Any image with a blacklisted tag will not be posted."""
        nsfw_db = await GuildNSFWDB.get_or_create(ctx.bot, ctx.guild.id)

        if not tag:
            if not nsfw_db.blacklisted_tags:
                raise commands.UserInputError("This server does not have any blacklisted tags.")

            e = mido_utils.Embed(ctx.bot, title=f"{ctx.guild} Blacklisted NSFW Tags")

            return await e.paginate(ctx, blocks=nsfw_db.blacklisted_tags, item_per_page=15)

        tag = tag.lower()

        if tag in nsfw_db.blacklisted_tags:
            raise commands.UserInputError(f"Tag `{tag}` is already blacklisted.")

        await nsfw_db.blacklist_tag(tag)

        await ctx.send_success(f"Tag `{tag}` has been successfully blacklisted.")

    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.command(name="tagwhitelist")
    async def whitelist_tag(self, ctx: mido_utils.Context, *, tag: str):
        """Whitelist/remove a blacklisted tag."""
        nsfw_db = await GuildNSFWDB.get_or_create(ctx.bot, ctx.guild.id)

        tag = tag.lower()

        if tag not in nsfw_db.blacklisted_tags:
            raise commands.UserInputError(f"Tag `{tag}` is not blacklisted.")

        await nsfw_db.whitelist_tag(tag)

        await ctx.send_success(f"Tag `{tag}` has been successfully removed from the blacklist.")


def setup(bot):
    bot.add_cog(NSFW(bot))
