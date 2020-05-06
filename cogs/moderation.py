from discord.ext import commands

from main import MidoBot


class Moderation(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    # TODO: moderation commands


def setup(bot):
    bot.add_cog(Moderation(bot))
