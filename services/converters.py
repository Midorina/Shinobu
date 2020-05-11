import discord
from discord.ext import commands


class BetterMemberconverter(commands.MemberConverter):
    async def convert(self, ctx, argument) -> discord.Member:
        try:
            member = await super().convert(ctx, argument)
        except commands.BadArgument:
            member = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.members)
            if not member:
                raise commands.BadArgument(f"Member \"{argument}\" not found.")

        return member
