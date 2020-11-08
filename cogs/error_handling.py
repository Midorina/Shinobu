import traceback

import discord
from discord.ext import commands

from services import exceptions as local_errors
from services.context import MidoContext


class Errors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: MidoContext, error):
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (
            discord.NotFound,
            local_errors.SilentError
        )

        error = getattr(error, 'original', error)

        try:
            if isinstance(error, ignored):
                return

            # this is to observe missing commands
            elif isinstance(error, commands.CommandNotFound):
                return self.bot.logger.info(f"Unknown command: {ctx.message.content} | {ctx.author} | {ctx.guild}")

            elif isinstance(error, commands.NSFWChannelRequired):
                return await ctx.send_error('This command can only be used in channels that are marked as NSFW.')

            elif isinstance(error, local_errors.InsufficientCash):
                return await ctx.send_error("You don't have enough money to do that!")

            elif isinstance(error, commands.NoPrivateMessage):
                return await ctx.send_error("This command can not be used through DMs!")

            elif isinstance(error, commands.NotOwner):
                return await ctx.send_error(error, "This is an owner-only command. Sorry.")

            elif isinstance(error, (commands.BotMissingPermissions, discord.Forbidden)):
                return await ctx.send_error(f"I do not have enough permissions to execute `{ctx.prefix}{ctx.command}`!")

            elif isinstance(error, commands.DisabledCommand):
                return await ctx.send_error("This command is currently disabled and can't be used.")

            elif isinstance(error, (commands.CommandOnCooldown, local_errors.OnCooldownError)):
                return await ctx.send_error(error, "You're on cooldown!")

            elif isinstance(error, commands.MissingRequiredArgument):
                return await ctx.send_help(entity=ctx.command, content=f"**You are missing this required argument: "
                                                                       f"`{error.param.name}`**")

            elif isinstance(error, commands.CheckFailure):
                return await ctx.send_error(error, "You don't have required permissions to do that!")

            elif isinstance(error, discord.HTTPException):
                if error.code == 0:
                    return await ctx.send_error("Discord API is currently having issues. Please use the command again.")

                elif error.code == 10014:
                    return await ctx.send_error(
                        "I don't have permission to use external emojis! Please give me permission to use them.")

            elif isinstance(error, local_errors.NotFoundError):
                return await ctx.send_error(error, "I couldn't find anything with that query.")

            elif isinstance(error, local_errors.RateLimited):
                return await ctx.send_error(error, "You are rate limited. Please try again in a few minutes.")

            elif isinstance(error, local_errors.APIError):
                return await ctx.send_error(error,
                                            "There was an error communicating with the API. Please try again later.")

            elif isinstance(error,
                            (commands.BadArgument,
                             commands.ExpectedClosingQuoteError,
                             commands.UnexpectedQuoteError,
                             commands.InvalidEndOfQuotedStringError)):
                return await ctx.send_help(entity=ctx.command, content=f"**{error}**")

            elif isinstance(error, (local_errors.MusicError,
                                    commands.UserInputError,
                                    local_errors.DidntVoteError)
                            ):
                return await ctx.send_error(error)

        except discord.Forbidden:
            return

        try:
            await ctx.send_error("**A critical error has occurred!** "
                                 "My developer will work on fixing this as soon as possible.")
        except discord.Forbidden:
            pass

        error_msg = "\n".join(traceback.format_exception(type(error), error, error.__traceback__))
        self.bot.logger.error(error_msg)

        if isinstance(ctx.channel, discord.DMChannel):
            used_in = f"DM {ctx.channel.id}"
        else:
            used_in = f"{ctx.channel.name}({ctx.channel.id}), guild {ctx.guild.name}({ctx.guild.id})"

        content = f"""
***ERROR ALERT*** <@{self.bot.config['owner_ids'][0]}>

An error occurred during the execution of a command:
`{str(error)}`

**Command:** `{ctx.invoked_with}`

**Command args:** `{ctx.args[2:]}`
**Command kwargs:** `{ctx.kwargs}`

**Command used by:** {ctx.author.mention} | `{str(ctx.author)}` | `{ctx.author.id}`
**Command used in:** `{used_in}`

**Message ID:** `{ctx.message.id}`
**Message link:** {ctx.message.jump_url}
**Message timestamp (UTC):** `{ctx.message.created_at}`

**Message contents:** `{ctx.message.content}`
"""

        traceback_embed = discord.Embed(title="Traceback", description=f"```py\n{error_msg[:2040]}```",
                                        timestamp=ctx.message.created_at, color=discord.Colour.red())

        await self.bot.log_channel.send(content=content, embed=traceback_embed)


def setup(bot):
    bot.add_cog(Errors(bot))
