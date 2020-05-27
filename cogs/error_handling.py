import traceback

import discord
from discord.ext import commands

from services.exceptions import EmbedError, SilenceError, NotFoundError


class Errors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (
            commands.CommandNotFound,
            discord.NotFound,
            NotFoundError,
            SilenceError
        )

        error = getattr(error, 'original', error)

        if isinstance(error, ignored):
            return

        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send_error("This command can not be used through DMs!")

        elif isinstance(error, discord.Forbidden):
            if error.code == 50013:
                await ctx.send_error("I don't have enough permissions!")
            else:
                raise error

        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send_error(f"I do not have enough permissions to execute `{ctx.prefix}{ctx.command}`!")

        elif isinstance(error, commands.DisabledCommand):
            await ctx.send_error("This command is currently disabled and can't be used.")

        elif isinstance(error, commands.CheckFailure):
            await ctx.send_error(":lock: You don't have required permissions to do that!")

        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send_error("You're on cooldown!")

        elif isinstance(error, EmbedError):
            await ctx.send_error(str(error))

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send_help(entity=ctx.command,
                                content=f"**You are missing this required argument: `{error.param.name}`**\n\u200b")

        elif isinstance(error, (commands.BadArgument, commands.ExpectedClosingQuoteError)):
            await ctx.send_help(entity=ctx.command,
                                content=f"**{error}**\n\u200b")

        elif isinstance(error, discord.HTTPException):
            if error.code == 0:
                await ctx.send_error("Discord API is currently having issues. Please use the command again.")

            elif error.code == 10014:
                await ctx.send_error(
                    "I don't have permission to use external emojis! Please give me permission to use them.")

        else:
            await ctx.send_error("**A critical error has occurred!** "
                                 "My developer will work on fixing this as soon as possible.")

            error_msg = "\n".join(traceback.format_exception(type(error), error, error.__traceback__))
            self.bot.logger.error(error_msg)

            if isinstance(ctx.channel, discord.DMChannel):
                used_in = f"DM {ctx.channel.id}"
            else:
                used_in = f"{ctx.channel.name}({ctx.channel.id}), guild {ctx.guild.name}({ctx.guild.id})"

            traceback_embed = discord.Embed(title="Traceback", description=f"```py\n{error_msg}```",
                                            timestamp=ctx.message.created_at, color=discord.Colour.red())

            await self.bot.log_channel.send(f"""
***ERROR ALERT*** <@90076279646212096>

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
""", embed=traceback_embed)


def setup(bot):
    bot.add_cog(Errors(bot))
