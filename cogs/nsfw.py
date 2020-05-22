import json
import random

import aiohttp
import discord
from discord.ext import commands

from main import MidoBot
from services.context import Context


class NotFoundError(Exception):
    pass


class NSFW(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.blacklisted_tags = [
            'loli',
            'shota',
            'child',
            'guro',
            'blood',
            'gore',
            'flat_chest'
        ]

        self.dapi_links = {
            'gelbooru': 'https://gelbooru.com/index.php',
            'rule34': 'https://rule34.xxx/index.php'
        }

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

    async def cog_check(self, ctx: Context):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            await ctx.send('This command can only be used in channels that are marked as NSFW.')
            return False

        return True

    @staticmethod
    async def get_boobs_or_butts(_type='boobs') -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://api.o{_type}.ru/noise/1/') as r:
                if r.status == 200:
                    data = await r.json()
                    return f"http://media.o{_type}.ru/" + data[0]['preview']
                else:
                    raise Exception('Couldn\t fetch image. Please try again later.')

    def clean_tags(self, tags):
        cleaned_tags = []
        for tag in tags:
            tag = tag.replace(' ', '_').lower()
            if tag.lower() not in self.blacklisted_tags:
                cleaned_tags.append(tag)

        return cleaned_tags

    async def get_nsfw_dapi(self, dapi='rule34', tags=None) -> str:
        tags = self.clean_tags(tags)
        max_range = 200 if dapi == 'gelbooru' else 2000

        async with aiohttp.ClientSession() as session:
            while True:
                rand_page = random.randrange(max_range) if max_range else 0

                async with session.get(self.dapi_links[dapi], params={
                    'page': 'dapi',
                    's': 'post',
                    'q': 'index',
                    'tags': "+".join(tags),
                    'limit': 100,
                    'json': 1,
                    'pid': rand_page,
                    # **self.bot.config['gelbooru_credentials']
                }) as response:
                    # lower the range
                    max_range = rand_page

                    if dapi == 'gelbooru':
                        response_jsond = await response.json() or []
                        filtered = list(filter(
                            lambda x: x['rating'] != 's' and not x['file_url'].endswith('.webm'),
                            response_jsond))

                        if not filtered:
                            # if we're at the last page
                            if rand_page == 0:
                                raise NotFoundError
                            else:
                                continue

                        data = random.choice(filtered)

                        image_url = data.get('file_url')
                        image_tags = data.get('tags').split(' ')

                    elif dapi == 'rule34':
                        r = await response.text()

                        response_jsond = json.loads(r)
                        filtered = list(filter(
                            lambda x: not x['image'].endswith('.webm'),
                            response_jsond))

                        if not filtered:
                            # if we're at the last page
                            if rand_page == 0:
                                raise NotFoundError
                            else:
                                continue

                        data = random.choice(filtered)
                        image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
                        image_tags = data.get('tags').split(' ')

                    # check if it contains a blacklisted tag
                    blacklisted = False
                    for tag in image_tags:
                        if tag in self.blacklisted_tags:
                            blacklisted = True
                            break

                    if blacklisted:
                        continue
                    else:
                        return image_url

    @commands.command(aliases=['boob'])
    async def boobs(self, ctx):
        """Get a random boob picture."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_boobs_or_butts(_type='boobs'))
        await ctx.send(embed=e)

    @commands.command(aliases=['butt'])
    async def butts(self, ctx):
        """Get a random butt picture."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_boobs_or_butts(_type='butts'))
        await ctx.send(embed=e)

    @commands.command()
    async def gelbooru(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        try:
            random_img = await self.get_nsfw_dapi('gelbooru', tags)
        except NotFoundError:
            return await ctx.send("No results.")

        e = discord.Embed(color=self.bot.main_color)
        e.set_footer(text="Gelbooru")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    @commands.command()
    async def rule34(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        try:
            random_img = await self.get_nsfw_dapi('rule34', tags)
        except NotFoundError:
            return await ctx.send("No results.")

        e = discord.Embed(color=self.bot.main_color,
                          description=f"If it doesn't load, click [here]({random_img}).")
        e.set_footer(text="Rule 34")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    # TODO: more hentai commands


def setup(bot):
    bot.add_cog(NSFW(bot))
