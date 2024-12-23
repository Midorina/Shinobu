import asyncio
import random

import discord
from discord.ext import commands, tasks

import mido_utils
from mido_utils.apis import NsfwDAPIs
from models.db import CachedImage, GuildNSFWDB, NSFWImage
from services import RedisCache
from shinobu import ShinobuBot


class NSFW(commands.Cog,
           description='Get quality NSFW images. '
                       'Check out `{ctx.prefix}autohentai` to have them posted automatically.'):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self._api = mido_utils.NsfwDAPIs(self.bot.http_session, self.bot)
        self.neko = mido_utils.NekosLifeAPI(session=self.bot.http_session, db=self.bot.db)

        self.reddit = mido_utils.RedditAPI(self.bot.config.reddit_credentials, self.bot.http_session, self.bot.db)

        self._cd: commands.CooldownMapping = commands.CooldownMapping.from_cooldown(
            rate=1, per=2, type=commands.BucketType.guild)

        self.active_auto_nsfw_services = list()
        self.start_auto_nsfw_task = self.bot.loop.create_task(self.start_auto_nsfw_services())

        if self.bot.config.reddit_automatically_pull_hot_posts:
            self.fetch_and_save_hot_posts_from_reddit.start()

        if self.bot.config.reddit_automatically_check_saved_posts:
            self.start_checking_urls_task = self.bot.loop.create_task(self.start_checking_urls_in_db())

        self.cache: RedisCache = RedisCache(self.bot)
        self.cache_expiration_in_seconds = 3600

    async def get_nsfw_image(self, nsfw_type: NSFWImage.Type, tags_str: str, limit=1, allow_video=True,
                             guild_id: int = None, nsfw_source: NsfwDAPIs.DAPI = None) -> list[NSFWImage]:
        tag_list = tags_str.replace(' ', '_').lower().split('+') if tags_str else []

        blacklisted_tags = await self._api.get_blacklisted_tags(guild_id)
        tag_list = list(filter(lambda x: x not in blacklisted_tags, tag_list))  # remove blacklisted tags
        tags_str = '+'.join(tag_list)  # build tags_str back

        allow_video = allow_video or 'video' in tags_str

        ret = []
        cache_key = (nsfw_source.name if nsfw_source else '') + nsfw_type.name + tags_str

        while len(ret) < limit:
            try:
                # if we don't have enough images in the cache, raise IndexError to get more images
                if limit >= await self.cache.get_length_of_set(cache_key):
                    raise IndexError

                pulled = NSFWImage.convert_from_cache(await self.cache.pop_random_from_set(cache_key))

                image_is_blacklisted = len(set(pulled.tags).intersection(blacklisted_tags)) > 0
                if not image_is_blacklisted:
                    ret.append(pulled)

            except (KeyError, IndexError):
                new_images = None

                # if porn is requested OR tags and a nsfw_source are not provided, pull from db
                if nsfw_type is NSFWImage.Type.porn or (not tags_str and not nsfw_source):
                    new_images = await self.reddit.get_reddit_post_from_db(
                        self.bot,
                        category=nsfw_type.name,
                        tags=[tags_str] if tags_str else None,
                        limit=500,
                        allow_gif=True)

                if not new_images:
                    if nsfw_type is NSFWImage.Type.porn:
                        raise mido_utils.IncompleteConfigFile(
                            "Reddit cache in the database is empty. "
                            "Please make sure you set up RedditAPI credentials properly in the config file "
                            "(If you are sure that credentials are correct, "
                            "please wait a bit for the database to be filled)."
                        )
                    elif nsfw_source:
                        new_images = await self._api.get(nsfw_source,
                                                         tags=tags_str,
                                                         limit=500,
                                                         allow_video=allow_video,
                                                         guild_id=guild_id)
                    else:
                        new_images = await self._api.get_bomb(tags=tags_str,
                                                              limit=500,
                                                              allow_video=allow_video,
                                                              guild_id=guild_id,
                                                              return_all=True)

                ret.append(new_images.pop())  # use one of the new images
                if new_images:  # add to cache if there are remaining new images
                    await self.cache.append_to_set(
                        cache_key,
                        self.cache_expiration_in_seconds,
                        *(image.cache_value for image in new_images)
                    )

                    # if a source is provided, add the images to the cache without the source key as well
                    # bad for us but good for external apis, this may be solved in a more efficient way
                    if nsfw_source:
                        await self.cache.append_to_set(
                            cache_key.replace(nsfw_source.name, ''),
                            3600,
                            *(image.cache_value for image in new_images)
                        )

        return ret

    async def start_checking_urls_in_db(self):
        await self.bot.wait_until_ready()

        self.bot.logger.info("Dead image checking service has started.")

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
                    self.bot.logger.debug(f"Checking image with URL '{image.url}' took:\t\t{time.passed_seconds_in_float_formatted}")
                    await asyncio.sleep(2.0)

            await asyncio.sleep(3.0)

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
        try:
            db_channel_id, db_tags, db_interval = guild.get_auto_nsfw_properties(nsfw_type)

            nsfw_channel = self.bot.get_channel(db_channel_id)

            fail_counter = 0
            while nsfw_channel and fail_counter < 5:  # if channel isn't found or set, code goes to the end
                time = mido_utils.Time()

                # DEBUGGING
                # cache_keys = await self.cache.get_keys()
                # image_count = sum([await self.cache.get_key_length(key) for key in cache_keys])
                # self.bot.logger.info(f"CACHE SIZE: {len(cache_keys)} keys, {image_count} images.")

                tags = random.choice(db_tags) if db_tags else None
                try:
                    try:
                        image = (await self.get_nsfw_image(
                            nsfw_type=nsfw_type, tags_str=tags, limit=1, guild_id=guild.id))[0]
                    except mido_utils.NotFoundError:
                        e = mido_utils.Embed(bot=self.bot,
                                             colour=discord.Colour.red(),
                                             description=f"Could  not find anything with tag: `{tags}`")
                        await nsfw_channel.send(embed=e)

                        fail_counter += 1
                        continue
                    else:
                        await self.bot.send_as_webhook(nsfw_channel, **image.get_send_kwargs(self.bot))
                except discord.Forbidden:
                    fail_counter = 5
                    break
                else:
                    fail_counter = 0

                self.bot.logger.debug(
                    f"Sending auto-{nsfw_type.name} took:\t\t{time.passed_seconds_in_float_formatted}")

                await asyncio.sleep(db_interval)

            if fail_counter >= 5 and nsfw_channel:
                e = mido_utils.Embed(bot=self.bot,
                                     colour=discord.Colour.red(),
                                     description=f"Too many failed attempts. Disabling auto-{nsfw_type.name}...")
                try:
                    await nsfw_channel.send(embed=e)
                except:
                    pass

            return await guild.set_auto_nsfw(nsfw_type=nsfw_type)  # reset

        except Exception:
            self.bot.logger.exception(
                f"Auto NSFW task of guild {guild.id} "
                f"for NSFW type {nsfw_type.name} "
                f"crashed due to the following exception:")

    @tasks.loop(hours=12.0)
    async def fetch_and_save_hot_posts_from_reddit(self):
        time = mido_utils.Time()

        # if credentials are set
        if hasattr(self.reddit, 'reddit'):
            await self.reddit.fill_the_database()

        self.bot.logger.debug('Checking hot posts from Reddit took:\t' + time.passed_seconds_in_float_formatted)

    @fetch_and_save_hot_posts_from_reddit.before_loop
    async def wait_for_bot_before_loop(self):
        await self.bot.wait_until_ready()

    @fetch_and_save_hot_posts_from_reddit.error
    async def task_error(self, error):
        await self.bot.get_cog('ErrorHandling').on_error(error)

    async def cog_check(self, ctx: mido_utils.Context):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after, type=self._cd.type)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            raise commands.NSFWChannelRequired(ctx.channel)

        return True

    def cog_unload(self):
        self.bot.loop.create_task(self.cache.disconnect())

        self.start_auto_nsfw_task.cancel()
        self.start_checking_urls_task.cancel()
        self.fetch_and_save_hot_posts_from_reddit.cancel()

        for task in self.active_auto_nsfw_services:
            task.cancel()

        self.active_auto_nsfw_services = list()

    @commands.command(aliases=['boob'])  # not hybrid because of slash command limit
    async def boobs(self, ctx: mido_utils.Context):
        """Get a random boob picture."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags_str='boobs', limit=1,
                                           guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(aliases=['butt', 'ass'])  # not hybrid because of slash command limit
    async def butts(self, ctx: mido_utils.Context):
        """Get a random butt picture."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags_str='butts', limit=1,
                                           guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()  # not hybrid because of slash command limit
    async def pussy(self, ctx: mido_utils.Context):
        """Get a random pussy image."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags_str='pussy', limit=1,
                                           guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.hybrid_command()
    async def asian(self, ctx: mido_utils.Context):
        """Get a random asian porn content."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags_str='asian', limit=1,
                                           guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()  # not hybrid because of slash command limit
    async def danbooru(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Danbooru.

        You must put '+' between different tags.
        `{ctx.prefix}danbooru yuri+group`

        **Danbooru doesn't allow more than 1 tag.**"""
        image = (await self.get_nsfw_image(
            nsfw_type=NSFWImage.Type.hentai, tags_str=tags, limit=1, guild_id=ctx.guild.id if ctx.guild else None,
            nsfw_source=NsfwDAPIs.DAPI.danbooru))[0]

        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command()  # not hybrid because of slash command limit
    async def gelbooru(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Gelbooru.

        You must put '+' between different tags.
        `{ctx.prefix}gelbooru yuri+group`"""
        image = (await self.get_nsfw_image(
            nsfw_type=NSFWImage.Type.hentai, tags_str=tags, limit=1, guild_id=ctx.guild.id if ctx.guild else None,
            nsfw_source=NsfwDAPIs.DAPI.gelbooru))[0]

        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(enabled=False)  # not hybrid because of slash command limit
    async def rule34(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Rule34.

        You must put '+' between different tags.
        `{ctx.prefix}rule34 yuri+group`"""

        image = (await self.get_nsfw_image(
            nsfw_type=NSFWImage.Type.hentai, tags_str=tags, limit=1, guild_id=ctx.guild.id if ctx.guild else None,
            nsfw_source=NsfwDAPIs.DAPI.rule34))[0]

        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.command(aliases=['sankakucomplex'])  # not hybrid because of slash command limit
    async def sankaku(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random image from Sankaku Complex.

        You must put '+' between different tags.
        `{ctx.prefix}sankaku yuri+group`

        **Sankaku Complex doesn't allow more than 3 tags.**"""
        image = (await self.get_nsfw_image(
            nsfw_type=NSFWImage.Type.hentai, tags_str=tags, limit=1, guild_id=ctx.guild.id if ctx.guild else None,
            nsfw_source=NsfwDAPIs.DAPI.sankaku_complex))[0]

        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.hybrid_command()
    async def porn(self, ctx: mido_utils.Context, *, tag: str = None):
        """Get a random porn content. A tag can be provided."""
        image = (await self.get_nsfw_image(nsfw_type=NSFWImage.Type.porn, tags_str=tag, limit=1,
                                           guild_id=ctx.guild.id if ctx.guild else None))[0]
        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.hybrid_command()
    async def hentai(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get a random hentai image.

        You must put '+' between different tags.
        `{ctx.prefix}hentai yuri+group`"""
        image = (await self.get_nsfw_image(
            nsfw_type=NSFWImage.Type.hentai, tags_str=tags, limit=1, guild_id=ctx.guild.id if ctx.guild else None))[0]

        await ctx.send(**image.get_send_kwargs(self.bot))

    @commands.hybrid_command(name='hentaibomb')
    async def hentai_bomb(self, ctx: mido_utils.Context, *, tags: str = None):
        """Get multiple hentai images.

        You must put '+' between different tags.
        `{ctx.prefix}hentaibomb yuri+group`"""
        images = await self.get_nsfw_image(
            NSFWImage.Type.hentai, tags, limit=3, allow_video=True, guild_id=ctx.guild.id if ctx.guild else None)
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

        if interval < 5:
            raise commands.UserInputError("Interval can not be less than 5!")

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
    @commands.hybrid_command(name='autohentai')
    @commands.bot_has_permissions(manage_webhooks=True)
    @mido_utils.is_patron_decorator(level=2)
    async def auto_hentai(self, ctx: mido_utils.Context, interval: mido_utils.Int32() = None, *, tags: str = None):
        """Have hentai automatically posted!

        Interval argument can be 5 seconds minimum.

        Put `+` between tags.
        Put `|` between tag groups. A random tag group will be chosen each time.
        (Tag argument can be left empty.)

        Don't type any argument to disable the autohentai service.

        Only 1 autohentai service can be active in a server.
        You need Manage Messages permission to use this command.

        `{ctx.prefix}autohentai 5`
        `{ctx.prefix}autohentai 7 yuri`
        `{ctx.prefix}autohentai 10 yuri+harem|futanari|blonde`"""

        await self.base_auto_nsfw_cmd(ctx, NSFWImage.Type.hentai, interval, tags)

    @commands.has_permissions(manage_messages=True)
    @commands.hybrid_command(name='autoporn')
    @commands.bot_has_permissions(manage_webhooks=True)
    @mido_utils.is_patron_decorator(level=2)
    async def auto_porn(self, ctx: mido_utils.Context, interval: mido_utils.Int32() = None, *, tags: str = None):
        """Have porn automatically posted!

        Interval argument can be 5 seconds minimum.

        Put `|` between tag groups. A random tag group will be chosen each time.
        Please provide a single tag for each tag group (unlike `autohentai`)
        (Tag argument can be left empty.)

        Don't type any argument to disable the autoporn service.

        Only 1 autoporn service can be active in a server.
        You need Manage Messages permission to use this command."""

        await self.base_auto_nsfw_cmd(ctx, NSFWImage.Type.porn, interval, tags)

    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.command(name="tagblacklist")  # not hybrid because of slash command limit
    async def blacklist_tag(self, ctx: mido_utils.Context, *, tag: str = None):
        """See the blacklisted tags or blacklist a tag. Provide a tag to blacklist it.
        Any image with a blacklisted tag will not be posted."""
        nsfw_db = await GuildNSFWDB.get_or_create(ctx.bot, ctx.guild.id)

        if not tag:
            blacklisted_from_backend = [f'{x} `[blacklisted from backend]`'
                                        for x in mido_utils.NsfwDAPIs.BLACKLISTED_TAGS]

            e = mido_utils.Embed(ctx.bot, title=f"{ctx.guild} Blacklisted NSFW Tags")

            return await e.paginate(ctx, blocks=blacklisted_from_backend + nsfw_db.blacklisted_tags, item_per_page=15)
        else:
            tag = tag.lower()

            if tag in nsfw_db.blacklisted_tags or tag in mido_utils.NsfwDAPIs.BLACKLISTED_TAGS:
                raise commands.UserInputError(f"Tag `{tag}` is already blacklisted.")

            await nsfw_db.blacklist_tag(tag)

            await ctx.send_success(f"Tag `{tag}` has been successfully blacklisted.")

    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.command(name="tagwhitelist")  # not hybrid because of slash command limit
    async def whitelist_tag(self, ctx: mido_utils.Context, *, tag: str):
        """Whitelist/remove a blacklisted tag."""
        nsfw_db = await GuildNSFWDB.get_or_create(ctx.bot, ctx.guild.id)

        tag = tag.lower()

        if tag not in nsfw_db.blacklisted_tags:
            raise commands.UserInputError(f"Tag `{tag}` is not blacklisted.")

        await nsfw_db.whitelist_tag(tag)

        await ctx.send_success(f"Tag `{tag}` has been successfully removed from the blacklist.")


async def setup(bot: ShinobuBot):
    # if bot.name == 'midobot':
    #     return

    await bot.add_cog(NSFW(bot))
