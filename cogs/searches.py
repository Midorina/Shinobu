import asyncurban
from discord.ext import commands

from main import MidoBot
from services import context, embed
from services.apis import Google


class Searches(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.google: Google = Google(self.bot.http_session)
        self.urban = asyncurban.UrbanDictionary(loop=self.bot.loop)

    @commands.cooldown(rate=1, per=5, type=commands.BucketType.guild)
    @commands.command(aliases=['g'])
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


def setup(bot):
    bot.add_cog(Searches(bot))
