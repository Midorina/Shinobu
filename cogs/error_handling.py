import sys
import traceback
from typing import Dict

import discord
from discord.ext import commands

import mido_utils
from ipc import ipc_errors
from shinobu import ShinobuBot


class ErrorHandling(commands.Cog):
    def __init__(self, bot: ShinobuBot):
        self.bot = bot

        self.cooldown_warning_cache: Dict[int, mido_utils.Time] = dict()

    # this doesn't fire as a listener
    async def on_error(self, event: str, *args, **kwargs):
        exception = sys.exc_info()

        self.bot.logger.exception(f"Internal Error: {event}", exc_info=exception)
        error_msg = "\n".join(traceback.format_exception(*exception))

        content = f"***INTERNAL ERROR ALERT*** <@{self.bot.config.owner_ids[0]}>\n" \
                  f"`{event}`"

        traceback_embed = discord.Embed(title=f"Traceback",
                                        color=mido_utils.Color.red(),
                                        description=f"```py\n{error_msg[-2000:]}```")

        await self.bot.ipc.send_to_log_channel(content=content, embed=traceback_embed)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: mido_utils.Context, error):
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (
            discord.NotFound,
            mido_utils.SilentError,
            mido_utils.GuildIsBlacklisted,
            mido_utils.UserIsBlacklisted
        )

        error = getattr(error, 'original', error)

        inform = True

        try:
            if isinstance(error, ignored):
                return

            # this is to observe missing commands
            elif mido_utils.better_is_instance(error, commands.CommandNotFound):
                return ctx.bot.logger.info(f"Unknown command: {ctx.message.content} | {ctx.author} | {ctx.guild}")

            elif mido_utils.better_is_instance(error, mido_utils.RaceError):
                return await ctx.send_error(error)

            elif mido_utils.better_is_instance(error, commands.NSFWChannelRequired):
                return await ctx.send_error('This command can only be used in channels that are marked as NSFW.')

            elif mido_utils.better_is_instance(error, mido_utils.InsufficientCash):
                return await ctx.send_error("You don't have enough money to do that!")

            elif mido_utils.better_is_instance(error, commands.NoPrivateMessage):
                return await ctx.send_error("This command can not be used through DMs!")

            elif mido_utils.better_is_instance(error, commands.errors.MaxConcurrencyReached):
                suffix = 'per %s' % error.per.name if error.per.name != 'default' else 'globally'
                plural = '%s times %s' if error.number > 1 else '%s time %s'
                fmt = plural % (error.number, suffix)
                return await ctx.send_error(f"This command can only be used {fmt}.")

            elif mido_utils.better_is_instance(error, commands.NotOwner):
                return await ctx.send_error(error, "This is an owner-only command. Sorry.")

            elif mido_utils.better_is_instance(error, commands.BotMissingPermissions):
                missing = [perm.replace('_', ' ').replace('guild', 'server').title() for perm in error.missing_perms]
                if len(missing) > 2:
                    fmt = '{}, and {}'.format(", ".join(missing[:-1]), missing[-1])
                else:
                    fmt = ' and '.join(missing)
                return await ctx.send_error(
                    f"I am missing these necessary permissions to execute `{ctx.prefix}{ctx.command}`:\n**{fmt}**")

            elif mido_utils.better_is_instance(error, discord.Forbidden):
                return await ctx.send_error("I am missing some necessary permissions to do what I need to do.")

            elif mido_utils.better_is_instance(error, commands.DisabledCommand):
                return await ctx.send_error("This command is temporarily disabled. Sorry for the inconvenience.")

            # cooldown errors
            # TODO: merge commands.CommandOnCooldown with mido_utils.OnCooldownError
            elif mido_utils.better_is_instance(error, commands.CommandOnCooldown):
                key = ctx.guild.id if ctx.guild else ctx.author.id
                should_send_message = True

                try:
                    next_warning = self.cooldown_warning_cache[key]
                    should_send_message = next_warning.end_date_has_passed

                    if should_send_message:
                        raise KeyError  # raise to re-set the key

                except KeyError:
                    self.cooldown_warning_cache[key] = mido_utils.Time.add_to_current_date_and_get(2)

                if should_send_message:
                    remaining = mido_utils.Time.parse_seconds_to_str(total_seconds=error.retry_after)
                    await ctx.send_error(f"You're on cooldown! Try again after **{remaining}**.")

                return

            elif mido_utils.better_is_instance(error, mido_utils.OnCooldownError):
                return await ctx.send_error(error, "You're on cooldown!")

            elif mido_utils.better_is_instance(error, commands.MissingRequiredArgument):
                return await ctx.send_help(entity=ctx.command, content=f"**You are missing this required argument: "
                                                                       f"`{error.param.name}`**")

            elif mido_utils.better_is_instance(error, commands.CheckFailure):
                return await ctx.send_error(error, "You don't have required permissions to do that!")

            elif mido_utils.better_is_instance(error, discord.HTTPException):
                if error.code == 0:
                    return await ctx.send_error("Discord API is currently having issues. Please use the command again.")

                elif error.code == 10014:
                    return await ctx.send_error(
                        "I don't have permission to use external emojis! Please give me permission to use them.")

            elif mido_utils.better_is_instance(error, mido_utils.NotFoundError):
                return await ctx.send_error(error, "I couldn't find anything with that query.")

            elif mido_utils.better_is_instance(error, mido_utils.RateLimited):
                return await ctx.send_error(error, "You are rate limited. Please try again in a few minutes.")

            elif mido_utils.better_is_instance(error, mido_utils.APIError):
                await ctx.send_error("There was an error communicating with the API. Please try again later.")
                inform = False

            elif mido_utils.better_is_instance(error, mido_utils.InvalidURL):
                return await ctx.send_error(error, "Invalid URL. Please specify a proper URL.")

            elif mido_utils.better_is_instance(error,
                                               (commands.BadArgument,
                                                commands.ExpectedClosingQuoteError,
                                                commands.UnexpectedQuoteError,
                                                commands.InvalidEndOfQuotedStringError)):
                return await ctx.send_help(entity=ctx.command, content=f"**{error}**")

            elif mido_utils.better_is_instance(
                    error, (mido_utils.MusicError,
                            commands.UserInputError,
                            mido_utils.TimedOut,
                            mido_utils.DidntVoteError,
                            mido_utils.UnknownCurrency,
                            mido_utils.NotPatron,
                            mido_utils.InsufficientPatronLevel,
                            mido_utils.CantClaimRightNow,
                            ipc_errors.RequestFailed,
                            mido_utils.IncompleteConfigFile)):
                return await ctx.send_error(error)

            if inform:
                await ctx.send_error("**A critical error has occurred!** "
                                     "My developer will work on fixing this as soon as possible.")

        except discord.Forbidden:
            return

        exc_info = type(error), error, error.__traceback__
        error_msg = "\n".join(traceback.format_exception(*exc_info))
        ctx.bot.logger.exception("Details of the last command error:", exc_info=exc_info)

        if mido_utils.better_is_instance(ctx.channel, discord.DMChannel):
            used_in = f"DM {ctx.channel.id}"
        else:
            used_in = f"{ctx.channel.name}({ctx.channel.id}), guild {ctx.guild.name}({ctx.guild.id})"

        # convert every arg to str to avoid this:
        # TypeError: __repr__ returned non-string (type int)
        ctx.args = list(map(lambda x: str(x), ctx.args))
        content = f"""
***ERROR ALERT*** <@{ctx.bot.config.owner_ids[0]}>

An error occurred during the execution of a command:
`{str(error)}` (Cluster **#{self.bot.cluster_id}**)

**Command:** `{ctx.invoked_with}`

**Command args:** `{str(ctx.args[2:])}`
**Command kwargs:** `{ctx.kwargs}`

**Command used by:** {ctx.author.mention} | `{str(ctx.author)}` | `{ctx.author.id}`
**Command used in:** `{used_in}`

**Message ID:** `{ctx.message.id}`
**Message link:** {ctx.message.jump_url}
**Message timestamp (UTC):** `{ctx.message.created_at}`

**Message contents:** `{ctx.message.content}`
"""

        traceback_embed = discord.Embed(title="Traceback", description=f"```py\n{error_msg[-2000:]}```",
                                        timestamp=ctx.message.created_at, color=mido_utils.Color.red())

        await ctx.bot.ipc.send_to_log_channel(content=content, embed=traceback_embed)


def setup(bot):
    bot.add_cog(ErrorHandling(bot))
