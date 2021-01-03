import discord
from discord.ext import commands

from mido_utils.context import Context


def ensure_role_hierarchy(ctx: Context):
    command_args = ctx.args + list(ctx.kwargs.values())
    role = next(arg for arg in command_args if isinstance(arg, discord.Role))

    # author top role check
    top_member_role = ctx.author.top_role
    if role.position >= top_member_role.position and ctx.guild.owner != ctx.author:
        raise commands.UserInputError(f"The position of {role.mention} is higher or equal "
                                      f"to your top role ({top_member_role.mention}). I can't proceed.")

    # bot top role check
    my_top_role = ctx.guild.me.top_role
    if role.position >= my_top_role.position:
        raise commands.UserInputError(f"The position of {role.mention} is higher or equal "
                                      f"to my top role ({my_top_role.mention}). I can't proceed.")


def is_owner():
    """This replaces the base `commands.is_owner()` to get rid of the weird error message:
    'You do not own this bot'
    """

    async def predicate(ctx):
        if not await ctx.bot.is_owner(ctx.author):
            raise commands.NotOwner
        return True

    return commands.check(predicate)
