import traceback

import discord
from discord.ext import commands

from main import MidoBot


class Errors(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        if hasattr(ctx.command, 'on_error'):
            return

        ignored = (
            commands.CommandNotFound,
            discord.NotFound,
        )

        error = getattr(error, 'original', error)

        if isinstance(error, ignored):
            return

        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command can not be used through DMs!")

        elif isinstance(error, discord.Forbidden):
            try:
                await ctx.send(
                    "I don't have required permissions! "
                    "Please check if I have permission to add reactions and see the message history of channels.")
            except discord.Forbidden:
                pass

        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"I do not have enough permissions to execute `{ctx.prefix}{ctx.command}`!")

        elif isinstance(error, commands.DisabledCommand):
            await ctx.send("This command is currently disabled and can not be used.")

        elif isinstance(error, commands.CheckFailure):
            await ctx.send(":lock: You don't have required permissions to do that!")

        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send("You're on cooldown!")

        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(
                f"You are missing required arguments!\n"
                f"`{error}`\n\n"
                f"Command usage:\n"
                f"**{ctx.prefix}{ctx.command.name} {ctx.command.signature}**")

        elif isinstance(error, (commands.BadArgument, commands.ExpectedClosingQuoteError)):
            await ctx.send(
                f"One of your arguments is incorrect!\n"
                f"`{error}`\n\n"
                f"Command usage:\n"
                f"**{ctx.prefix}{ctx.command.name} {ctx.command.signature}**")

        else:
            if isinstance(error, discord.HTTPException):
                if error.code == 0:
                    return await ctx.send("Discord API is currently having issues. Please use the command again.")

                elif error.code == 10014:
                    return await ctx.send(
                        "I don't have permission to use external emojis! Please give me permission to use them.")

            embed = discord.Embed(
                description="**A fatal error has occured!** Please be patient for a solution to be found.")
            await ctx.send(embed=embed)

            # self.bot.logger.error('Ignoring exception in command {}:'.format(ctx.command))
            # traceback.print_exception(type(error), error, error.__traceback__, file=sys.stderr)

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
`{error}`

**Command:** `{ctx.invoked_with}`

**Command args:** `{ctx.args[2:]}`
**Command kwargs:** `{ctx.kwargs}`

**Command used by:** {ctx.author.mention} | `{str(ctx.author)}` | `{ctx.author.id}`
**Command used in:** `{used_in}`

**Message id:** `{ctx.message.id}`
**Message link:** {ctx.message.jump_url}
**Message timestamp (UTC):** `{ctx.message.created_at}`

**Message contents:** `{ctx.message.content}`""", embed=traceback_embed)


def setup(bot):
    bot.add_cog(Errors(bot))
