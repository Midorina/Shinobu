from discord.ext import commands

from main import MidoBot


class Searches(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    # TODO: google, urban dictionary


def setup(bot):
    bot.add_cog(Searches(bot))
