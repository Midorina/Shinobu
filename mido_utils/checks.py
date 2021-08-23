import discord
from discord.ext import commands

import mido_utils
import models


def ensure_role_hierarchy(ctx, role: discord.Role = None):
    command_args = ctx.args + list(ctx.kwargs.values())

    try:
        role = role or next(arg for arg in command_args if isinstance(arg, discord.Role))
    except StopIteration:
        return

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


def is_patron_decorator(level: int = 1, allow_owner=True):
    async def predicate(ctx):
        return await is_patron(bot=ctx.bot, user_id=ctx.author.id,
                               required_level=level, allow_owner=allow_owner,
                               raise_exceptions=True)

    return commands.check(predicate)


async def is_patron(bot, user_id: int, required_level: int = 1, allow_owner=True, raise_exceptions=False) -> bool:
    if allow_owner is True and user_id in bot.owner_ids:
        return True

    patron: models.UserAndPledgerCombined = await bot.ipc.get_patron(user_id)
    if not patron:
        if raise_exceptions is True:
            raise mido_utils.NotPatron(f'Unfortunately this command is exclusive to the supporters :/\n\n'
                                       f'You can unlock this command by '
                                       f'[supporting the project.]({mido_utils.links.patreon})')
        else:
            return False
    elif patron.level_status.level < required_level:
        if raise_exceptions is True:
            raise mido_utils.InsufficientPatronLevel(
                "Unfortunately your membership level is insufficient to run this command.")
        else:
            return False
    return True
