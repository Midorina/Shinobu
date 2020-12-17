from discord.ext import commands

import mido_utils
from models.db import BlacklistDB


class Blacklist(commands.Cog, command_attrs=dict(hidden=True)):
    def __init__(self, bot):
        self.bot = bot

    async def bot_check(self, ctx: mido_utils.Context):
        user_is_blacklisted = await BlacklistDB.get(bot=ctx.bot, user_or_guild_id=ctx.author.id, type='user')

        guild_is_blacklisted = False
        if ctx.guild is not None:
            guild_is_blacklisted = await BlacklistDB.get(bot=ctx.bot, user_or_guild_id=ctx.guild.id, type='guild')
            # if the guild owner is blacklisted but the guild is not blacklisted
            # blacklist their guild too, fuck'em
            if user_is_blacklisted and ctx.author.id == ctx.guild.owner.id and not guild_is_blacklisted:
                await BlacklistDB.blacklist(bot=ctx.bot,
                                            user_or_guild_id=ctx.guild.id,
                                            type='guild',
                                            reason=f'Automatically blacklisted because the owner {ctx.author.id} was blacklisted')
                guild_is_blacklisted = True

        if user_is_blacklisted:
            raise mido_utils.UserIsBlacklisted("The user is blacklisted.")
        if guild_is_blacklisted:
            raise mido_utils.GuildIsBlacklisted("The guild is blacklisted.")

        return True

    @mido_utils.is_owner()
    @commands.command(aliases=["bl"])
    async def blacklist(self, ctx: mido_utils.Context, type: str, _id: mido_utils.Int64(), *, reason: str = None):
        """Blacklists a guild or a user (and every server they own)."""
        if type not in ('user', 'guild'):
            return await ctx.send_error("Invalid blacklist type. Please use `user` or `guild`.")

        is_blacklisted = await BlacklistDB.get(bot=ctx.bot,
                                               user_or_guild_id=_id,
                                               type=type)
        if is_blacklisted:
            return await ctx.send_error(f"{type.title()} `{_id}` is already blacklisted!")

        await BlacklistDB.blacklist(bot=ctx.bot,
                                    user_or_guild_id=_id,
                                    type=type,
                                    reason=reason or f'Blacklisted by the owner {ctx.author.id}')

        if type == 'user':
            counter = 0
            for guild in self.bot.guilds:
                if guild.owner.id == _id:
                    counter += 1
                    await BlacklistDB.blacklist(bot=ctx.bot,
                                                user_or_guild_id=guild.id,
                                                type="guild",
                                                reason=f'Automatically blacklisted because the owner {_id} has been blacklisted by the owner {ctx.author.id}')

            await ctx.send_success(f"Successfully blacklisted the user <@{_id}> and **{counter}** servers they have.")
        else:
            await ctx.send_success(f"Successfully blacklisted the server `{_id}`.")

    @mido_utils.is_owner()
    @commands.command(aliases=["ubl"])
    async def unblacklist(self, ctx: mido_utils.Context, type: str, _id: mido_utils.Int64()):
        """Removes a blacklisted guild or a user (and every server they own)."""
        if type not in ('user', 'guild'):
            return await ctx.send_error("Invalid blacklist type. Please use `user` or `guild`.")

        is_blacklisted = await BlacklistDB.get(bot=ctx.bot,
                                               user_or_guild_id=_id,
                                               type=type)
        if not is_blacklisted:
            return await ctx.send_error(f"{type.title()} `{_id}` is not blacklisted!")

        await BlacklistDB.unblacklist(bot=ctx.bot,
                                      user_or_guild_id=_id,
                                      type=type)

        if type == 'user':
            counter = 0
            for guild in self.bot.guilds:
                if guild.owner.id == _id:
                    counter += 1
                    await BlacklistDB.unblacklist(bot=ctx.bot,
                                                  user_or_guild_id=guild.id,
                                                  type="guild")

            await ctx.send_success(f"Successfully unblacklisted the user <@{_id}> and **{counter}** servers they have.")
        else:
            await ctx.send_success(f"Successfully unblacklisted the server `{_id}`.")


def setup(bot):
    bot.add_cog(Blacklist(bot))
