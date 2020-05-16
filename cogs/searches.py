from discord.ext import commands

from main import MidoBot
from services import context, base_embed
from services.google_search import Google


class Searches(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    # async def get_urban_search(self):

    @commands.command(aliases=['g'])
    async def google(self, ctx: context.Context, *, search: str):
        results = await Google().search(query=search)
        e = base_embed.BaseEmbed(self.bot)

        for result in results[:10]:
            e.add_field(name=result.title if result.title else "None",
                        value=f"[{result.url}]({result.url})",
                        inline=False)

        await ctx.send(embed=e)

    # TODO: urban dictionary


def setup(bot):
    bot.add_cog(Searches(bot))
