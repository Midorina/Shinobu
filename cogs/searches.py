import asyncurban
from discord.ext import commands

from main import MidoBot
from services import context, base_embed, menu_stuff
from services.google_search import Google


class Searches(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.urban = asyncurban.UrbanDictionary(loop=self.bot.loop)

    @commands.command(aliases=['g'])
    async def google(self, ctx: context.Context, *, search: str):
        """Makes a Google search."""

        results = await Google().search(query=search)
        e = base_embed.BaseEmbed(self.bot)

        for result in results[:10]:
            e.add_field(name=result.title if result.title else "None",
                        value=f"[{result.url}]({result.url})",
                        inline=False)

        await ctx.send(embed=e)

    @commands.command(aliases=['u', 'urbandictionary', 'ud'])
    async def urban(self, ctx: context.Context, *, search: str):
        """Searches the definition of a word on UrbanDictionary."""

        try:
            word_list = await self.urban.search(search, limit=5)
        except asyncurban.WordNotFoundError:
            return await ctx.send("Could not find any definition.")
        blocks = list()

        e = base_embed.BaseEmbed(self.bot)
        for word in word_list:
            base = f"**[{word.word}]({word.permalink})**\n\n{word.definition.replace('[', '**').replace(']', '**')}"

            if word.example:
                base += f"\n\n**Example:**\n\n{word.example.replace('[', '**').replace(']', '**')}"

            blocks.append(base)

        await menu_stuff.paginate(self.bot, ctx, embed=e, blocks=blocks, item_per_page=1)


def setup(bot):
    bot.add_cog(Searches(bot))
