import discord
from discord.ext import commands

from db.models import UserDB, GuildDB, MemberDB
from services.base_embed import BaseEmbed


class MidoContext(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = self.bot.db

        self.guild_db: GuildDB = None
        self.member_db: MemberDB = None
        self.user_db: UserDB = None

    async def attach_db_objects(self):
        try:
            self.member_db = await MemberDB.get_or_create(self.db, self.guild.id, self.author.id)
            self.guild_db = self.member_db.guild
            self.user_db = self.member_db.user

            self.prefix = self.guild_db.prefix
        except AttributeError:
            self.user_db = await UserDB.get_or_create(self.db, self.author.id)

    async def send_error(self, error_message: str):
        embed = BaseEmbed(bot=self.bot,
                          color=discord.Colour.red(),
                          description=error_message,
                          footer=False)
        return await self.send(embed=embed)

    async def send_success(self, sucess_message: str):
        embed = BaseEmbed(bot=self.bot,
                          description=sucess_message)
        return await self.send(embed=embed)

    @staticmethod
    async def edit_custom(message_object: discord.Message, new_message: str):
        embed = message_object.embeds[0]
        embed.description = new_message
        await message_object.edit(embed=embed)

    async def send_help(self, entity=None, content=''):
        """This method overwrites the library's method to provide extra content to the help message."""
        from discord.ext.commands import Group, Command, CommandError
        from discord.ext.commands.core import wrap_callback

        bot = self.bot
        cmd = bot.help_command

        if cmd is None:
            return None

        cmd = cmd.copy()
        cmd.context = self
        if not entity:
            await cmd.prepare_help_command(self, None)
            mapping = cmd.get_bot_mapping()
            injected = wrap_callback(cmd.send_bot_help)
            try:
                return await injected(mapping)
            except CommandError as e:
                await cmd.on_help_command_error(self, e)
                return None

        if entity is None:
            return None

        if isinstance(entity, str):
            entity = bot.get_cog(entity) or bot.get_command(entity)

        if not hasattr(entity, 'qualified_name'):
            # it's not a cog, group, or command.
            return None

        await cmd.prepare_help_command(self, entity.qualified_name)

        try:
            if hasattr(entity, '__cog_commands__'):
                injected = wrap_callback(cmd.send_cog_help)
                return await injected(entity)
            elif isinstance(entity, Group):
                injected = wrap_callback(cmd.send_group_help)
                return await injected(entity)
            elif isinstance(entity, Command):
                injected = wrap_callback(cmd.send_command_help)
                return await injected(entity, content=content)
            else:
                return None
        except CommandError as e:
            await cmd.on_help_command_error(self, e)
