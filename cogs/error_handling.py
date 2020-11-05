import traceback

import discord
from discord.ext import commands

from services.exceptions import EmbedError, InsufficientCash, MusicError, NotFoundError, SilenceError


class Errors(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (
            # commands.CommandNotFound,
            discord.NotFound,
            NotFoundError,
            SilenceError
        )

        error = getattr(error, 'original', error)

        if isinstance(error, ignored):
            return

        # this is to observe missing commands
        elif isinstance(error, commands.CommandNotFound):
            return self.bot.logger.info(f"Unknown command: {ctx.message.content}")

        elif isinstance(error, InsufficientCash):
            return await ctx.send_error("You don't have enough money to do that!")

        elif isinstance(error, commands.NoPrivateMessage):
            return await ctx.send_error("This command can not be used through DMs!")

        elif isinstance(error, discord.Forbidden):
            try:
                return await ctx.send_error("I don't have enough permissions!")
            except discord.Forbidden:
                pass

        elif isinstance(error, commands.BotMissingPermissions):
            return await ctx.send_error(f"I do not have enough permissions to execute `{ctx.prefix}{ctx.command}`!")

        elif isinstance(error, commands.DisabledCommand):
            return await ctx.send_error("This command is currently disabled and can't be used.")

        elif isinstance(error, commands.CheckFailure):
            return await ctx.send_error("You don't have required permissions to do that!")

        elif isinstance(error, commands.CommandOnCooldown):
            return await ctx.send_error("You're on cooldown!")

        elif isinstance(error, (EmbedError, MusicError)):
            return await ctx.send_error(str(error))

        elif isinstance(error, commands.MissingRequiredArgument):
            return await ctx.send_help(entity=ctx.command,
                                       content=f"**You are missing this required argument: "
                                               f"`{error.param.name}`**")

        elif isinstance(error,
                        (commands.BadArgument, commands.ExpectedClosingQuoteError, commands.UnexpectedQuoteError)):
            return await ctx.send_help(entity=ctx.command,
                                       content=f"**{error}**")

        elif isinstance(error, discord.HTTPException):
            if error.code == 0:
                return await ctx.send_error("Discord API is currently having issues. Please use the command again.")

            elif error.code == 10014:
                return await ctx.send_error(
                    "I don't have permission to use external emojis! Please give me permission to use them.")

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
