from datetime import datetime

from discord.ext import commands

from services.context import MidoContext
from services.embed import MidoEmbed


class MidoHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(command_attrs={
            'cooldown': commands.Cooldown(rate=1, per=1.0, type=commands.BucketType.member),
            'help'    : 'Shows help about the bot or a command.',
            'aliases' : ['h']
        })
        self.verify_checks = False

    def command_not_found(self, string):
        return f'Couldn\'t find any command called `{string}`'

    async def on_help_command_error(self, ctx: MidoContext, error):
        if isinstance(error, commands.CommandInvokeError):
            await ctx.send(str(error.original))

    def get_command_signature(self, command):
        parent = command.full_parent_name

        if len(command.aliases) > 0:
            aliases = '|'.join(command.aliases)
            fmt = f'[{command.name}|{aliases}]'
            if parent:
                fmt = f'{parent} {fmt}'
            alias = fmt
        else:
            alias = command.name if not parent else f'{parent} {command.name}'

        return f'{alias} {command.signature}'

    async def send_bot_help(self, mapping):
        import itertools

        def key(c):
            return c.cog_name or '\u200bNo Category'

        entries = await self.filter_commands(self.context.bot.commands, sort=True, key=key)
        total = 0

        e = MidoEmbed(self.context.bot,
                      title='MidoBot Commands',
                      description=f'You can type `{self.context.prefix}help <command>` '
                                  f'to see additional info about a command.',
                      default_footer=True)
        for cog, _commands in itertools.groupby(entries, key=key):
            _commands = sorted(_commands, key=lambda c: c.name)
            if len(_commands) == 0:
                continue

            total += len(_commands)
            e.add_field(name=f"**__{str(cog)}__**",
                        value="\n".join([f'{self.context.prefix}**{c.name}**' for c in _commands]),
                        inline=True)

        e.set_footer(text=f"{total} Commands",
                     icon_url=self.context.bot.user.avatar_url)
        e.timestamp = datetime.utcnow()

        await self.context.send(embed=e)

    def common_command_formatting(self, embed, command):
        embed.title = self.context.prefix + self.get_command_signature(command)
        if command.description:
            embed.description = f'{command.description}\n\n{command.help}'
        else:
            if not command.help:
                embed.description = 'There\'s no help information about this command...'
            else:
                embed.description = command.help.format(self.context)

    async def send_command_help(self, command, content=''):
        if command.hidden:
            raise commands.CommandInvokeError("That is a hidden command. Sorry.")

        embed = MidoEmbed(self.context.bot, default_footer=True)
        self.common_command_formatting(embed, command)
        await self.context.send(content=content, embed=embed)
