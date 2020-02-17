from discord.ext import commands
from datetime import datetime, timezone


class XP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def add_xp(self, message, amount, reason="None"):
        time = datetime.now(timezone.utc)
        await self.bot.db.execute(
            """UPDATE users SET xp = xp + $1, last_xp_gained = $2 where server_id=$3 and user_id=$4""",
            amount, time, message.guild.id, message.author.id
        )

        self.bot.logger.debug(f"{time} : User {message.author.name} has just gained {amount} XP. Reason: {reason}")

        await self.check_for_level_up(message, added=amount)


def setup(bot):
    bot.add_cog(XP(bot))
