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

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

    async def cog_check(self, ctx: Context):
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

    async def get_gelbooru(self, tags) -> str:
        tags = self.clean_tags(tags)
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get('https://gelbooru.com/index.php', params={
                    'page': 'dapi',
                    's': 'post',
                    'q': 'index',
                    'tags': "+".join(tags),
                    'limit': 100,
                    'json': 1,
                    'pid': random.randrange(200),
                    **self.bot.config['gelbooru_credentials']
                }) as response:
                    response_jsond = await response.json()
                    if not response_jsond:
                        continue
                    data = random.choice(list(filter(
                        lambda x:  x['rating'] != 's' and x['file_url'].split('.')[-1] != '.webm',
                        response_jsond)))
                    # print(data.get('file_url'), data.get('rating'), data.get('tags'), sep='\n')
                    image_url = data.get('file_url')
                    tags = data.get('tags').split(' ')

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

    @commands.command()
    async def boobs(self, ctx):
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_boobs_or_butts(type='boobs'))
        await ctx.send(embed=e)

    @commands.command()
    async def butts(self, ctx):
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_boobs_or_butts(type='butts'))
        await ctx.send(embed=e)

    @commands.command()
    async def gelbooru(self, ctx, *tags):
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.get_gelbooru(tags))
        await ctx.send(embed=e)

    # TODO: more hentai commands


def setup(bot):
    bot.add_cog(NSFW(bot))
