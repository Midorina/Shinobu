import discord
from discord.ext import commands

from main import MidoBot
from services.apis import NSFWAPIs, NotFoundError
from services.context import MidoContext


class NSFW(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.api = NSFWAPIs(self.bot.db)

        self._cd = commands.CooldownMapping.from_cooldown(rate=2, per=1, type=commands.BucketType.guild)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, NotFoundError):
            return await ctx.send("No results.")

    async def cog_check(self, ctx: MidoContext):
        bucket = self._cd.get_bucket(ctx.message)
        retry_after = bucket.update_rate_limit()
        if retry_after:  # if on cooldown
            raise commands.CommandOnCooldown(bucket, retry_after)

        if not isinstance(ctx.channel, discord.DMChannel) and not ctx.channel.is_nsfw():
            await ctx.send('This command can only be used in channels that are marked as NSFW.')
            return False

        return True

    @commands.command(aliases=['boob'])
    async def boobs(self, ctx):
        """Get a random boob picture."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.api.get('boobs'))
        await ctx.send(embed=e)

    @commands.command(aliases=['butt'])
    async def butts(self, ctx):
        """Get a random butt picture."""
        e = discord.Embed(color=self.bot.main_color)
        e.set_image(url=await self.api.get('butts'))
        await ctx.send(embed=e)

    @commands.command()
    async def gelbooru(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        random_img = await self.api.get('gelbooru', tags)

        e = discord.Embed(color=self.bot.main_color)
        e.set_footer(text="Gelbooru")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    @commands.command()
    async def rule34(self, ctx, *tags):
        """Get a random image from Gelbooru."""
        random_img = await self.api.get('rule34', tags)

        e = discord.Embed(color=self.bot.main_color,
                          description=f"If it doesn't load, click [here]({random_img}).")
        e.set_footer(text="Rule 34")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    @commands.command()
    async def danbooru(self, ctx, *tags):
        """Get a random image from Danbooru."""
        random_img = await self.api.get('danbooru', tags)

        e = discord.Embed(color=self.bot.main_color)
        e.set_footer(text="Danbooru")
        e.set_image(url=random_img)
        await ctx.send(embed=e)

    # TODO: more hentai commands


def setup(bot):
    bot.add_cog(NSFW(bot))
