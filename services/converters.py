import discord
from discord.ext import commands

from services.context import MidoContext


class MidoMemberConverter(commands.MemberConverter):
    async def convert(self, ctx: MidoContext, argument) -> discord.Member:
        try:
            member = await super().convert(ctx, argument)
        except commands.BadArgument:
            if argument.isdigit():
                member = ctx.bot.get_user(int(argument))
            else:  # if its a string
                member = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.members)

            if not member:
                raise commands.BadArgument(f"Member \"{argument}\" not found.")

        return member


class MidoRoleConverter(commands.RoleConverter):
    async def convert(self, ctx: MidoContext, argument) -> discord.Role:
        try:
            role = await super().convert(ctx, argument)
        except commands.BadArgument:
            role = discord.utils.find(lambda m: m.name.lower() == argument.lower(), ctx.guild.roles)

        if not role:
            raise commands.BadArgument(f"Role \"{argument}\" not found.")

        return role


def readable_bigint(number: int) -> str:
    return '{:,}'.format(number)
