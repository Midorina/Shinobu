import asyncurban
from discord.ext import commands

from midobot import MidoBot
from services import context, embed
from services.apis import Google, SomeRandomAPI
from services.embed import MidoEmbed


# TODO: pokemon, hearthstone

class Searches(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.google: Google = Google(self.bot.http_session)
        self.urban = asyncurban.UrbanDictionary(loop=self.bot.loop)
        self.some_random_api = SomeRandomAPI(self.bot.http_session)

    @commands.command()
    async def color(self, ctx: context.MidoContext, *, color: str):
        """Get a color image from specified hex."""
        color_str = color.replace('#', '')
        color = int(color_str, 16)

        e = MidoEmbed(ctx.bot, image_url=self.some_random_api.view_color(color_str), colour=color)

        await ctx.send(embed=e)

    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.command(aliases=['g'], enabled=False)  # todo
    async def google(self, ctx: context.MidoContext, *, search: str):
        """Makes a Google search."""

        results = await self.google.search(query=search)
        e = embed.MidoEmbed(self.bot)
        e.set_author(icon_url="https://w7.pngwing.com/pngs/506/509/png-transparent-google-company-text-logo.png",
                     name=f"Google: {search}")

        e.description = ""
        for result in results[:5]:
            e.add_field(name=result.url_simple,
                        value=f"[{result.title}]({result.url})\n"
                              f"{result.description}\n‎\n",
                        inline=False)

        await ctx.send(embed=e)

    @commands.cooldown(rate=1, per=3, type=commands.BucketType.guild)
    @commands.command(aliases=['u', 'urbandictionary', 'ud'])
    async def urban(self, ctx: context.MidoContext, *, search: str):
        """Searches the definition of a word on UrbanDictionary."""

        try:
            word_list = await self.urban.search(search, limit=5)
        except asyncurban.WordNotFoundError:
            return await ctx.send("Could not find any definition.")

        blocks = list()

        e = embed.MidoEmbed(self.bot)
        for word in word_list:
            base = f"**[{word.word}]({word.permalink})**\n\n{word.definition.replace('[', '**').replace(']', '**')}"

            if word.example:
                base += f"\n\n**Example:**\n\n{word.example.replace('[', '**').replace(']', '**')}"

            blocks.append(base)

        await e.paginate(ctx, blocks=blocks, item_per_page=1)

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command(aliases=['dog', 'woof'])
    async def doggo(self, ctx: context.MidoContext):
        """Get a random doggo picture."""
        await ctx.send_simple_image(await self.some_random_api.get_animal("dog"))

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command(aliases=['cat', 'meow'])
    async def catto(self, ctx: context.MidoContext):
        """Get a random catto picture."""
        await ctx.send_simple_image(await self.some_random_api.get_animal("cat"))

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command()
    async def panda(self, ctx: context.MidoContext):
        """Get a random panda picture."""
        await ctx.send_simple_image(await self.some_random_api.get_animal("panda"))

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command()
    async def fox(self, ctx: context.MidoContext):
        """Get a random fox picture."""
        await ctx.send_simple_image(await self.some_random_api.get_animal("fox"))

    @commands.cooldown(rate=1, per=0.5, type=commands.BucketType.guild)
    @commands.command(aliases=['birb'])
    async def bird(self, ctx: context.MidoContext):
        """Get a random bird picture."""
        await ctx.send_simple_image(await self.some_random_api.get_animal("bird"))


def setup(bot):
    bot.add_cog(Searches(bot))
