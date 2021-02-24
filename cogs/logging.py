from datetime import datetime
from enum import Enum, auto
from io import StringIO
from typing import List, Optional, Union

import discord
from discord.ext import commands, tasks

import mido_utils
from midobot import MidoBot
from models.db import GuildLoggingDB, LoggedMessage


class LoggedEvents(Enum):
    MEMBER_JOIN = auto()
    MEMBER_REMOVE = auto()

    ROLE_CREATE = auto()
    ROLE_DELETE = auto()
    CHANNEL_CREATE = auto()
    CHANNEL_DELETE = auto()

    MESSAGE_EDIT = auto()
    MESSAGE_DELETE = auto()
    MESSAGE_DELETE_BULK = auto()

    VOICE_STATE_UPDATE = auto()


class Logging(commands.Cog):
    def __init__(self, bot: MidoBot):
        self.bot = bot

        self.message_cache = list()
        self.cache_to_db_task.start()

    async def insert_cache_to_db(self):
        to_db, self.message_cache = self.message_cache, []
        await LoggedMessage.insert_bulk(self.bot, to_db)

    @tasks.loop(minutes=1.0)
    async def cache_to_db_task(self):
        await self.bot.wait_until_ready()
        await self.insert_cache_to_db()

    @cache_to_db_task.after_loop
    async def on_cache_to_db_cancel(self):
        if self.cache_to_db_task.is_being_cancelled() and len(self.message_cache) != 0:
            await self.insert_cache_to_db()

    @cache_to_db_task.error
    async def on_cache_to_db_error(self, error):
        await self.bot.get_cog('ErrorHandling').on_error(error)

    async def get_cached_message(self, message_id: int) -> Union[discord.Message, LoggedMessage, None]:
        for msg in self.message_cache:
            if msg.id == message_id:
                return msg

        return await LoggedMessage.get(bot=self.bot, message_id=message_id)

    async def get_cached_message_bulk(self, message_ids: List[int]) -> List[
        Union[discord.Message, LoggedMessage, None]]:
        ret = []
        for msg in self.message_cache:
            if msg.id in message_ids:
                ret.append(msg)
                message_ids.remove(msg.id)

        if message_ids:  # if there are messages left
            ret.extend(await LoggedMessage.get_bulk(self.bot, message_ids))

        return ret

    def cog_unload(self):
        self.cache_to_db_task.cancel()

    @staticmethod
    def detailed(obj: Union[discord.Member, discord.Role, discord.TextChannel]) -> str:
        return f'{obj.mention} (**{str(obj)}**, `{obj.id}`)'

    def get_member_event_embed(self, member: discord.Member) -> mido_utils.Embed:
        e = mido_utils.Embed(bot=self.bot)
        e.set_author(icon_url=member.avatar_url, name=str(member))
        e.set_footer(text=f"User ID: {member.id}")
        e.timestamp = datetime.utcnow()

        return e

    def get_guild_event_embed(self, guild: discord.Guild) -> mido_utils.Embed:
        e = mido_utils.Embed(bot=self.bot)
        e.set_author(icon_url=guild.icon_url, name=str(guild))
        e.timestamp = datetime.utcnow()

        return e

    def get_guild_id_out_of_event(self, arg):
        if isinstance(arg, (discord.Role, discord.Member)):
            return arg.guild.id
        elif isinstance(arg, (discord.RawMessageDeleteEvent, discord.RawBulkMessageDeleteEvent)):
            return arg.guild_id
        elif isinstance(arg, discord.RawMessageUpdateEvent):
            try:
                return self.bot.get_channel(arg.channel_id).guild.id
            except AttributeError:
                return None

    async def base_logging_func(self, logging_type: LoggedEvents, *args):
        guild_id = self.get_guild_id_out_of_event(args[0])
        if not guild_id:
            return

        guild_settings = await GuildLoggingDB.get_or_create(bot=self.bot, guild_id=guild_id)
        if not guild_settings.logging_is_enabled:
            return

        e = None
        content = None
        file = None
        time = '`[{}]`'.format(mido_utils.Time.get_now().start_date_string)

        if logging_type is LoggedEvents.MEMBER_JOIN:
            member: discord.Member = args[0]
            account_creation_date = mido_utils.Time(start_date=member.created_at, offset_naive=True)
            if guild_settings.simple_mode_is_enabled:
                e = self.get_member_event_embed(member)
                e.title = "Member Joined"
                e.description = self.detailed(member)

                e.add_field(name="Joined Discord at",
                            value=f"{account_creation_date.start_date_string}\n"
                                  f"({account_creation_date.remaining_days} days ago)",
                            inline=True)
            else:
                content = f"{time} :inbox_tray: {self.detailed(member)} joined the server. " \
                          f"Account age: {account_creation_date.remaining_days} days"

        elif logging_type is LoggedEvents.MEMBER_REMOVE:
            member: discord.Member = args[0]
            if guild_settings.simple_mode_is_enabled:
                e = self.get_member_event_embed(member)
                e.title = "Member Left"
                e.description = self.detailed(member)
            else:
                content = f"{time} :outbox_tray: {self.detailed(member)} left the server."

        elif logging_type is LoggedEvents.VOICE_STATE_UPDATE:
            member: discord.Member
            before: Optional[discord.VoiceState]
            after: Optional[discord.VoiceState]
            member, before, after = args
            if before.channel == after.channel:
                # if its just an event inside the same channel (like mute, deafen etc), return
                return

            if guild_settings.simple_mode_is_enabled:
                e = self.get_member_event_embed(member)

                if before.channel is None:
                    e.description = f"{member.mention} joined voice channel: **{after.channel}**"
                elif after.channel is None:
                    e.description = f"{member.mention} left voice channel: **{before.channel}**"
                else:
                    e.description = f"{member.mention} switched voice channels: **{before.channel}** -> **{after.channel}**"

            else:
                if before.channel is None:
                    content = f"{time} :microphone: :blue_circle: " \
                              f"{self.detailed(member)} joined voice channel: **{after.channel}**"
                elif after.channel is None:
                    content = f"{time} :microphone: :red_circle: " \
                              f"{self.detailed(member)} left voice channel: **{before.channel}**"
                else:
                    content = f"{time} :microphone: :left_right_arrow: " \
                              f"{self.detailed(member)} switched voice channels: **{before.channel}** -> **{after.channel}**"

        elif logging_type is LoggedEvents.ROLE_CREATE or logging_type is LoggedEvents.ROLE_DELETE:
            role = args[0]
            keyword = "Created" if logging_type is LoggedEvents.ROLE_CREATE else "Deleted"
            if guild_settings.simple_mode_is_enabled:
                e = self.get_guild_event_embed(guild=role.guild)
                e.description = f"**Role {keyword}:** {str(role)}"
                e.set_footer(text=f"Role ID: {role.id}")
            else:
                content = f"{time} :pen_ballpoint: Role {keyword}: {self.detailed(role)}"

        elif logging_type is LoggedEvents.CHANNEL_CREATE or logging_type is LoggedEvents.CHANNEL_DELETE:
            channel = args[0]
            keyword = "Created" if logging_type is LoggedEvents.CHANNEL_CREATE else "Deleted"
            if guild_settings.simple_mode_is_enabled:
                e = self.get_guild_event_embed(channel.guild)
                e.description = f"**Channel {keyword}:** #{str(channel)}"
                e.set_footer(text=f"Channel ID: {channel.id}")
            else:
                content = f"{time} :pen_ballpoint: Channel {keyword}: {self.detailed(channel)})"

        elif logging_type is LoggedEvents.MESSAGE_DELETE \
                or logging_type is LoggedEvents.MESSAGE_EDIT:
            payload: Union[discord.RawMessageDeleteEvent, discord.RawMessageUpdateEvent] = args[0]

            if not payload.cached_message:
                # todo: handle message not being in the cache
                msg = await self.get_cached_message(message_id=payload.message_id)
            else:
                msg: discord.Message = payload.cached_message

            if logging_type is LoggedEvents.MESSAGE_EDIT:
                new_msg = await msg.channel.fetch_message(msg.id)
                if new_msg.content == msg.content:
                    # if the contents are identical, return
                    return

                if guild_settings.simple_mode_is_enabled:
                    e = self.get_member_event_embed(msg.author)
                    e.description = f"**Message sent by {msg.author.mention} in {msg.channel.mention} " \
                                    f"has just been edited.** [Jump]({msg.jump_url})\n" \
                                    f"**Before:**\n" \
                                    f"{msg.content}\n" \
                                    f"**After:**\n" \
                                    f"{new_msg.content}"
                    e.set_footer(text=f"Author ID: {msg.author.id} | Message ID: {msg.id}")
                else:
                    content = f"{time} :x: {self.detailed(msg.author)} edited their message (`{msg.id}`) " \
                              f"in {self.detailed(msg.channel)}.\n" \
                              f"**Before:**\n" \
                              f"```{msg.content}```\n" \
                              f"**After:**\n" \
                              f"```{new_msg.content}```"
            else:
                if guild_settings.simple_mode_is_enabled:
                    e = self.get_member_event_embed(msg.author)
                    e.description = f"**Message sent by {msg.author.mention} in {msg.channel.mention} " \
                                    f"has just been deleted. Message Content:**\n{msg.content}"
                    e.set_footer(text=f"Author ID: {msg.author.id} | Message ID: {msg.id}")
                else:
                    content = f"{time} :x: Message `{msg.id}` sent by {self.detailed(msg.author)} " \
                              f"in {self.detailed(msg.channel)} has just been deleted.\n"
                    if msg.content:
                        content += f"**Message Content:**\n```{msg.content}```\n"
                    if msg.embeds:
                        content += "**Message Embed:**"
                        e = msg.embeds[0]

        elif logging_type is LoggedEvents.MESSAGE_DELETE_BULK:
            payload: discord.RawBulkMessageDeleteEvent = args[0]
            channel: discord.TextChannel = self.bot.get_channel(payload.channel_id)

            if not payload.cached_messages:
                msgs = await self.get_cached_message_bulk(payload.message_ids)
            else:
                msgs: List[discord.Message] = list(payload.cached_messages)

            # prepare the log file
            s = StringIO()
            for message in msgs:
                date = '[{}]'.format(message.created_at.strftime('%Y-%m-%d, %H:%M:%S UTC'))
                author = f"{message.author} ({message.author.id})"
                s.write(f"{date} {author}: {message.content}\n")
            s.seek(0)

            time_for_file = mido_utils.Time.get_now().start_date.strftime('%Y_%m_%d-%H_%M_%SUTC')
            file = discord.File(s, filename=f"{time_for_file}--{len(msgs)} Messages.txt")

            if guild_settings.simple_mode_is_enabled:
                e = self.get_guild_event_embed(channel.guild)
                e.description = f"**{len(msgs)} messages have been deleted in {channel.mention}.**\n" \
                                f"They are included in the text file below."
            else:
                content = f"{time} :x: {len(msgs)} messages have been deleted in {self.detailed(channel)}."

        await guild_settings.logging_channel.send(content=content,
                                                  embed=e,
                                                  file=file,
                                                  allowed_mentions=discord.AllowedMentions.none())

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.guild:
            self.message_cache.append(msg)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.base_logging_func(LoggedEvents.MEMBER_JOIN, member)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        await self.base_logging_func(LoggedEvents.MEMBER_REMOVE, member)

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        await self.base_logging_func(LoggedEvents.ROLE_CREATE, role)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        await self.base_logging_func(LoggedEvents.ROLE_DELETE, role)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.TextChannel):
        await self.base_logging_func(LoggedEvents.CHANNEL_CREATE, channel)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.TextChannel):
        await self.base_logging_func(LoggedEvents.CHANNEL_DELETE, channel)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        await self.base_logging_func(LoggedEvents.MESSAGE_DELETE, payload)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        await self.base_logging_func(LoggedEvents.MESSAGE_EDIT, payload)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        await self.base_logging_func(LoggedEvents.MESSAGE_DELETE_BULK, payload)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: Optional[discord.VoiceState],
                                    after: Optional[discord.VoiceState]):
        await self.base_logging_func(LoggedEvents.VOICE_STATE_UPDATE, member, before, after)

    @commands.command(aliases=['log'])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def logging(self, ctx: mido_utils.Context):
        """Disable or enable logging in the current channel.
        Use `{0.prefix}loggingmode` to change between simple and advanced logging.

        You need Administrator permission to use this command."""
        guild_settings = await GuildLoggingDB.get_or_create(bot=self.bot, guild_id=ctx.guild.id)
        if not guild_settings.logging_is_enabled:
            await guild_settings.set_log_channel(ctx.channel.id)
            await ctx.send_success(f"You've successfully **enabled logging** in {ctx.channel.mention}.")
        else:
            await guild_settings.set_log_channel(None)  # disable
            await ctx.send_success("You've successfully **disabled logging**.")

    @commands.command(aliaseS=['logmode'])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    async def loggingmode(self, ctx: mido_utils.Context):
        """Swap logging mode (basic or advanced)"""
        guild_settings = await GuildLoggingDB.get_or_create(bot=self.bot, guild_id=ctx.guild.id)
        if guild_settings.simple_mode_is_enabled:
            await guild_settings.change_mode_to_simple(False)
            await ctx.send_success(f"You've successfully change the logging mode to **advanced**.")
        else:
            await guild_settings.change_mode_to_simple(True)
            await ctx.send_success(f"You've successfully change the logging mode to **simple**.")


def setup(bot):
    bot.add_cog(Logging(bot))