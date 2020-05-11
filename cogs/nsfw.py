import json
import random

import aiohttp
import discord
from discord.ext import commands

from main import MidoBot
from services.context import Context


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
        print(1)
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            return False

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            await ctx.send('This command can only be used in channels that are marked as NSFW.')
            return False

        return True

    @staticmethod
    async def get_boobs_or_butts(type='boobs') -> str:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://api.o{type}.ru/noise/1/') as r:
                if r.status == 200:
                    data = await r.json()
                    return f"http://media.o{type}.ru/" + data[0]['preview']
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
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(self.dapi_links[dapi], params={
                    'page': 'dapi',
                    's': 'post',
                    'q': 'index',
                    'tags': "+".join(tags),
                    'limit': 100,
                    'json': 1,
                    'pid': random.randrange(200) if dapi == 'gelbooru' else random.randrange(2000),
                    **self.bot.config['gelbooru_credentials']
                }) as response:
                    if dapi == 'gelbooru':
                        response_jsond = await response.json()
                        data = random.choice(list(filter(
                            lambda x: x['rating'] != 's' and x['file_url'].split('.')[-1] != '.webm',
                            response_jsond)))

                        image_url = data.get('file_url')
                        tags = data.get('tags').split(' ')

                    elif dapi == 'rule34':
                        r = await response.text()
                        response_jsond = json.loads(r)
                        filtered = list(filter(
                            lambda x: x['image'].split('.')[-1] != '.webm',
                            response_jsond))
                        if not filtered:
                            continue
                        data = random.choice(filtered)
                        image_url = f"https://img.rule34.xxx/images/{data.get('directory')}/{data.get('image')}"
                        tags = data.get('tags').split(' ')

                    print(image_url, data.get('rating'), data.get('tags'), sep='\n')
                    # check if it contains a blacklisted tag
                    blacklisted = False
                    for tag in tags:
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
        e.set_image(url=await self.get_boobs_or_butts(type='boobs'))
        await ctx.send(embed=e)

    @commands.command(aliases=['butt'])
    async def butts(self, ctx):
        """Get a random butt picture."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_boobs_or_butts(type='butts'))
        await ctx.send(embed=e)

    @commands.command()
    async def gelbooru(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_footer(text="Gelbooru")
        e.set_image(url=await self.get_nsfw_dapi('gelbooru', tags))
        await ctx.send(embed=e)

    @commands.command()
    async def rule34(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        random_img = await self.get_nsfw_dapi('rule34', tags)
        e = discord.Embed(color=self.bot.main_color,
                          description=f"If it doesn't load, click [here]({random_img}).")
        e.set_footer(text="Rule 34")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    # TODO: more hentai commands


def setup(bot):
    bot.add_cog(NSFW(bot))
