from discord.ext import commands

from services.context import MidoContext


class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def hangman(self, ctx: MidoContext, category: str):
        # todo
        pass


def setup(bot):
    bot.add_cog(Games(bot))
