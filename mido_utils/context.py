from typing import Union

import discord
from asyncpg.pool import Pool
from discord.ext import commands

import mido_utils
import models


class Context(commands.Context):
    # noinspection PyTypeChecker
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db: Pool = self.bot.db

        # FOR TYPE HINTING
        from shinobu import ShinobuBot
        self.bot: ShinobuBot

        self.guild_db: models.GuildDB = None
        self.member_db: models.MemberDB = None
        self.user_db: models.UserDB = None

        self.voice_player: mido_utils.VoicePlayer = None

        self.time_created: mido_utils.Time = mido_utils.Time()

    async def attach_db_objects(self):
        time = mido_utils.Time()
        try:
            self.member_db = await models.MemberDB.get_or_create(self.bot, self.guild.id, self.author.id)

            # guild stuff
            self.guild_db = self.member_db.guild
            self.prefix = self.guild_db.prefix

            self.user_db = self.member_db.user
        except AttributeError:  # not in guild
            self.user_db = await models.UserDB.get_or_create(self.bot, self.author.id)

        self.bot.logger.debug('Attaching db objects to ctx took:\t' + time.passed_seconds_in_float_formatted)

    async def send_error(self,
                         error_obj: Union[Exception, str],
                         message_to_show_if_no_msg_is_included: str = 'Error!') -> discord.Message:
        msg = str(error_obj) or message_to_show_if_no_msg_is_included

        embed = mido_utils.Embed(bot=self.bot,
                                 color=mido_utils.Color.red(),
                                 description=msg)

        return await self.send(embed=embed)

    async def send_success(self, message: str = 'Success!', delete_after: float = None, **kwargs) -> discord.Message:
        embed = mido_utils.Embed(bot=self.bot,
                                 description=message,
                                 **kwargs)

        return await self.send(embed=embed, delete_after=delete_after)

    @staticmethod
    async def edit_custom(message_object: discord.Message, new_message: str):
        embed = message_object.embeds[0]
        embed.description = new_message
        await message_object.edit(embed=embed)

    async def send_simple_image(self, url: str):
        e = mido_utils.Embed(bot=self.bot, image_url=url)
        await self.send(embed=e)

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
