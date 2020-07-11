import discord

from services.context import MidoContext
from services.exceptions import EmbedError


def ensure_role_hierarchy(ctx: MidoContext):
    role = None
    for arg in ctx.args:
        if isinstance(arg, discord.Role):
            role = arg
            break

    # author top role check
    top_member_role = ctx.author.top_role
    if role.position >= top_member_role.position and ctx.guild.owner != ctx.author:
        raise EmbedError(f"The position of {role.mention} is higher or equal "
                         f"to your top role ({top_member_role.mention}). I can't proceed.")

    # bot top role check
    my_top_role = ctx.guild.me.top_role
    if role.position >= my_top_role.position:
        raise EmbedError(f"The position of {role.mention} is higher or equal "
                         f"to my top role ({my_top_role.mention}). I can't proceed.")
