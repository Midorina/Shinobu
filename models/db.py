from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Set, Union

import asyncpg
import discord
from asyncpg import Record
from discord.ext.commands import BadArgument

import mido_utils
from models.waifu import Waifu


class XpAnnouncement(Enum):
    SILENT = 0
    DM = 1
    GUILD = 2


class BaseDBModel:
    def __init__(self, data: Record, bot):
        self.bot = bot
        self.db = self.bot.db

        self.data = data

        self.id = data.get('id')

        self.date_added = data.get('date_added')

    def __eq__(self, other):
        raise NotImplemented


class ModLog(BaseDBModel):
    class Type(Enum):
        MUTE = 0
        UNMUTE = 1
        KICK = 1
        BAN = 2
        UNBAN = 3

    def __init__(self, modlog_db: Record, bot):
        super(ModLog, self).__init__(modlog_db, bot)

        self.guild_id = modlog_db.get('guild_id')
        self.user_id = modlog_db.get('user_id')

        self.type = ModLog.Type(modlog_db.get('type'))
        self.reason = modlog_db.get('reason')
        self.executor_id = modlog_db.get('executor_id')

        self.length_string = mido_utils.Time.parse_seconds_to_str(modlog_db.get('length_in_seconds'))
        self.time_status = mido_utils.Time.add_to_previous_date_and_get(
            modlog_db.get('date'), modlog_db.get('length_in_seconds')
        )

        self.done = modlog_db.get('done')

    @classmethod
    async def get_by_id(cls, bot, guild_id: int, log_id: int):
        log = await bot.db.fetchrow("""SELECT * FROM modlogs WHERE id=$1 AND guild_id=$2;""", log_id, guild_id)

        return cls(log, bot) if log else None

    @classmethod
    async def get_guild_logs(cls, bot, guild_id: int, user_id: int):
        logs = await bot.db.fetch(
            """SELECT * FROM modlogs WHERE guild_id=$1 AND user_id=$2 AND hidden=FALSE ORDER BY date DESC;""",
            guild_id, user_id)

        return [cls(log, bot) for log in logs]

    @classmethod
    async def get_open_logs(cls, bot):
        ret = await bot.db.fetch(
            """
            SELECT 
                *
            FROM 
                modlogs 
            WHERE 
                length_in_seconds IS NOT NULL AND length_in_seconds != 0
                AND type = ANY($1) 
                AND done IS NOT TRUE;""", (ModLog.Type.MUTE.value, ModLog.Type.BAN.value))

        return [cls(x, bot) for x in ret]

    @classmethod
    async def add_modlog(cls,
                         bot,
                         guild_id: int,
                         user_id: int,
                         _type: Type,
                         executor_id: int,
                         reason: str = None,
                         length: mido_utils.Time = None,
                         ):
        new_modlog_db = await bot.db.fetchrow(
            """INSERT INTO 
            modlogs (guild_id, user_id, type, reason, executor_id, length_in_seconds, date) 
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *;""",
            guild_id,
            user_id,
            _type.value,
            reason,
            executor_id,
            getattr(length, 'remaining_seconds', None),
            datetime.now(timezone.utc)
        )

        return cls(new_modlog_db, bot)

    async def delete_from_db(self):
        await self.db.execute("""DELETE FROM modlogs WHERE id=$1;""", self.id)

    async def complete(self):
        await self.db.execute("""UPDATE modlogs SET done=TRUE WHERE id=$1;""", self.id)

    async def change_reason(self, new_reason: str):
        await self.db.execute("""UPDATE modlogs SET reason=$1 WHERE id=$2;""", new_reason, self.id)

    @staticmethod
    async def hide_logs(bot, guild_id: int, user_id: int):
        await bot.db.execute(
            """UPDATE modlogs SET hidden=TRUE WHERE guild_id=$1 AND user_id=$2;""", guild_id, user_id)

    def __eq__(self, other):
        if isinstance(other, ModLog):
            return self.id == other.id


def calculate_xp_data(total_xp: int):
    base_xp = 30
    used_xp = 0
    lvl = 1

    while True:
        required_xp_to_level_up = int(base_xp + base_xp / 3.0 * (lvl - 1))

        if required_xp_to_level_up + used_xp > total_xp:
            break

        used_xp += required_xp_to_level_up
        lvl += 1

    return lvl, total_xp - used_xp, required_xp_to_level_up


class UserDB(BaseDBModel):
    def __init__(self, user_db: Record, bot):
        super(UserDB, self).__init__(user_db, bot)

        self.cash: int = user_db.get('cash')

        self._discord_name = user_db.get('name_and_discriminator') or self.id

        self.level_up_notification = XpAnnouncement(user_db.get('level_up_notification'))
        self.total_xp: int = user_db.get('xp')
        self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
        self.xp_status = mido_utils.Time.add_to_previous_date_and_get(
            user_db.get('last_xp_gain'), bot.config['cooldowns']['xp']
        )

        self.daily_date_status = mido_utils.Time.add_to_previous_date_and_get(user_db.get('last_daily_claim'),
                                                                              bot.config['cooldowns']['daily'])

        self.waifu: Waifu = Waifu(self)

    @property
    def discord_name(self) -> str:
        user = self.bot.get_user(self.id)
        if user:
            if str(user) != self._discord_name:  # name cache check
                self.bot.loop.create_task(self.update_name(new_name=str(user)))

            return str(user)
        else:
            return self._discord_name

    @property
    def discord_obj(self) -> discord.User:
        return self.bot.get_user(self.id)

    @classmethod
    async def get_or_create(cls, bot, user_id: int):
        user_db = await bot.db.fetchrow("""SELECT * FROM users WHERE id=$1;""", user_id)
        if not user_db:
            try:
                user_db = await bot.db.fetchrow("""INSERT INTO users (id) VALUES($1) RETURNING *;""", user_id)
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, user_id)

        local_obj = cls(user_db, bot)

        return local_obj

    @classmethod
    async def get_rich_people(cls, bot, limit=100):
        ret = await bot.db.fetch("SELECT * FROM users ORDER BY cash DESC LIMIT $1;", limit)
        return [cls(user_db, bot) for user_db in ret]

    @property
    def cash_str_without_emoji(self) -> str:
        from mido_utils.converters import readable_bigint
        return readable_bigint(self.cash)

    @property
    def cash_str(self) -> str:
        from mido_utils.converters import readable_currency
        return readable_currency(self.cash)

    async def update_name(self, new_name: str):
        self._discord_name = new_name
        await self.db.execute("UPDATE users SET name_and_discriminator=$1 WHERE id=$2;", new_name, self.id)

    async def change_level_up_preference(self, new_preference: XpAnnouncement):
        await self.db.execute(
            """UPDATE users SET level_up_notification=$1 WHERE id=$2;""",
            new_preference.value, self.id)

    async def add_cash(self, amount: int, reason: str, daily=False):
        if amount == 0:
            return

        self.cash += amount

        if daily:
            await self.db.execute(
                """UPDATE users SET cash = cash + $1, last_daily_claim=$2 WHERE id=$3;""",
                amount, datetime.now(timezone.utc), self.id)
        else:
            await self.db.execute(
                """UPDATE users SET cash = cash + $1 WHERE id=$2;""",
                amount, self.id)

        await self.db.execute("""INSERT INTO transaction_history(user_id, amount, reason) VALUES ($1, $2, $3);""",
                              self.id, amount, reason)

    async def remove_cash(self, amount: int, reason: str, force=False):
        if force is False and self.cash < amount:
            raise mido_utils.InsufficientCash

        await self.add_cash(amount=0 - amount, reason=reason)

    async def add_xp(self, amount: int, owner=False) -> int:
        if not self.xp_status.end_date_has_passed and not owner:
            raise mido_utils.OnCooldownError(f"You're still on cooldown! "
                                             f"Try again after **{self.xp_status.remaining_string}**.")
        else:
            await self.db.execute(
                """UPDATE users SET xp = xp + $1, last_xp_gain = $2 WHERE id=$3""",
                amount, datetime.now(timezone.utc), self.id)

            self.total_xp += amount
            # im just too lazy
            self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
            return self.total_xp

    async def remove_xp(self, amount: int) -> int:
        await self.db.execute(
            """UPDATE users SET xp = xp - $1 WHERE id=$2""",
            amount, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self.db.fetchrow("""
            WITH counts AS (
                SELECT DISTINCT
                    id,
                    ROW_NUMBER () OVER (ORDER BY xp DESC)
                FROM
                    users
            ) SELECT
                *
            FROM
                counts
            WHERE
                id=$1;
            """, self.id)

        return result['row_number']

    @classmethod
    async def get_top_10(cls, bot):
        top_10 = await bot.db.fetch("""SELECT * FROM users ORDER BY xp DESC LIMIT 10;""")
        return [UserDB(user, bot) for user in top_10]

    @classmethod
    async def get_claimed_waifus_by(cls, user_id: int, bot) -> List:
        ret = await bot.db.fetch("SELECT * FROM users WHERE waifu_claimer_id=$1;", user_id)
        return [cls(user, bot) for user in ret]

    @classmethod
    async def get_top_expensive_waifus(cls, limit: int, bot):
        ret = await bot.db.fetch(
            "SELECT * FROM users WHERE waifu_price IS NOT NULL ORDER BY waifu_price DESC LIMIT $1;", limit)
        return [cls(user, bot) for user in ret]

    async def delete(self):
        await self.db.execute("DELETE FROM users WHERE id=$1;", self.id)
        await self.db.execute("DELETE FROM members WHERE user_id=$1;", self.id)

    def __eq__(self, other):
        if isinstance(other, UserDB):
            return self.id == other.id


class MemberDB(BaseDBModel):
    # noinspection PyTypeChecker
    def __init__(self, member_db: Record, bot):
        super(MemberDB, self).__init__(member_db, bot)

        self.id = member_db.get('user_id')

        self.guild: GuildDB = None
        self.user: UserDB = None

        self.total_xp: int = member_db.get('xp')

        self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
        self.xp_date_status = mido_utils.Time.add_to_previous_date_and_get(
            member_db.get('last_xp_gain'), bot.config['cooldowns']['xp'])

    @property
    def discord_name(self):
        return self.user.discord_name

    @classmethod
    async def get_or_create(cls, bot, guild_id: int, member_id: int):
        member_db = await bot.db.fetchrow(
            """SELECT * FROM members WHERE guild_id=$1 AND user_id=$2;""", guild_id, member_id)

        if not member_db:
            try:
                member_db = await bot.db.fetchrow(
                    """INSERT INTO members (guild_id, user_id) VALUES($1, $2) RETURNING *;""", guild_id, member_id)
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, guild_id, member_id)

        user_db = await UserDB.get_or_create(bot, member_id)
        guild_db = await GuildDB.get_or_create(bot, guild_id)

        member_obj = cls(member_db, bot)
        member_obj.guild = guild_db
        member_obj.user = user_db

        return member_obj

    async def add_xp(self, amount: int, owner=False) -> int:
        if not self.xp_date_status.end_date_has_passed and not owner:
            raise mido_utils.OnCooldownError(f"You're still on cooldown! "
                                             f"Try again after **{self.xp_date_status.remaining_string}**.")
        else:
            await self.db.execute(
                """UPDATE members SET xp = xp + $1, last_xp_gain = $2 WHERE guild_id=$3 AND user_id=$4""",
                amount, datetime.now(timezone.utc), self.guild.id, self.id)

            self.total_xp += amount
            # im just too lazy
            self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
            return self.total_xp

    async def remove_xp(self, amount: int) -> int:
        await self.db.execute(
            """UPDATE members SET xp = xp - $1 WHERE guild_id=$2 AND user_id=$3;""",
            amount, self.guild.id, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self.db.fetchrow("""
            WITH counts AS (
                SELECT DISTINCT
                    guild_id,
                    user_id,
                    ROW_NUMBER () OVER (ORDER BY xp DESC)
                FROM
                    members
                WHERE
                    guild_id=$1
            ) SELECT
                *
            FROM
                counts
            WHERE
                user_id=$2;
            """, self.guild.id, self.id)

        return result['row_number']

    def __eq__(self, other):
        if isinstance(other, MemberDB):
            return self.id == other.id


class GuildDB(BaseDBModel):
    def __init__(self, guild_db: Record, bot):
        super(GuildDB, self).__init__(guild_db, bot)

        self.prefix: str = guild_db.get('prefix')

        self.delete_commands: bool = guild_db.get('delete_commands')
        self.level_up_notifs_silenced: bool = guild_db.get('level_up_notifs_silenced')
        self.last_message_date: mido_utils.Time = mido_utils.Time(guild_db.get('last_message_date'))
        self.xp_excluded_channels: List[int] = guild_db.get('xp_excluded_channels')

        # welcome
        self.welcome_channel_id: int = guild_db.get('welcome_channel_id')
        self.welcome_message: str = guild_db.get('welcome_message')
        self.welcome_delete_after: int = guild_db.get('welcome_delete_after') or None
        # bye
        self.bye_channel_id: int = guild_db.get('bye_channel_id')
        self.bye_message: str = guild_db.get('bye_message')
        self.bye_delete_after: int = guild_db.get('bye_delete_after') or None

        # assignable roles
        self.assignable_role_ids: List[int] = guild_db.get('assignable_role_ids')
        self.assignable_roles_are_exclusive: bool = guild_db.get('exclusive_assignable_roles')

        # music
        self.volume: int = guild_db.get('volume')

        # auto hentai
        self.auto_hentai_channel_id: int = guild_db.get('auto_hentai_channel_id')
        self.auto_hentai_tags: List[str] = guild_db.get('auto_hentai_tags')
        self.auto_hentai_interval: int = guild_db.get('auto_hentai_interval')

        # auto porn
        self.auto_porn_channel_id: int = guild_db.get('auto_porn_channel_id')
        self.auto_porn_tags: List[str] = guild_db.get('auto_porn_tags')
        self.auto_porn_interval: int = guild_db.get('auto_porn_interval')

    @classmethod
    async def get_guilds_that_are_active_in_last_x_hours(cls, bot, hours: int = 24):
        ret = await bot.db.fetch("SELECT * FROM guilds WHERE last_message_date > (now() - $1::interval);",
                                 timedelta(hours=hours))

        return [cls(guild, bot) for guild in ret]

    @staticmethod
    async def update_active_guilds(bot, guild_id_list: List[int]):
        await bot.db.execute("UPDATE guilds SET last_message_date=now() WHERE id=ANY($1);", guild_id_list)

    @classmethod
    async def get_or_create(cls, bot, guild_id: int):
        guild_db = await bot.db.fetchrow("""SELECT * FROM guilds WHERE id=$1;""", guild_id)
        if not guild_db:
            try:
                guild_db = await bot.db.fetchrow(
                    """INSERT INTO guilds(id, prefix) VALUES ($1, $2) RETURNING *;""",
                    guild_id, bot.config['default_prefix'])
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, guild_id)

        return cls(guild_db, bot)

    @classmethod
    async def get_auto_nsfw_guilds(cls, bot):
        ret = await bot.db.fetch("SELECT * FROM guilds "
                                 "WHERE auto_hentai_channel_id IS NOT NULL "
                                 "OR auto_porn_channel_id IS NOT NULL;")
        return [cls(guild, bot) for guild in ret]

    async def change_prefix(self, new_prefix: str):
        self.prefix = new_prefix
        self.bot.prefix_cache[self.id] = new_prefix  # update cache

        await self.db.execute(
            """UPDATE guilds SET prefix=$1 WHERE id=$2;""", new_prefix, self.id)

    async def change_volume(self, new_volume: int):
        await self.db.execute("""UPDATE guilds SET volume=$1 WHERE id=$2;""", new_volume, self.id)
        self.volume = new_volume

    async def toggle_delete_commands(self) -> bool:
        await self.db.execute(
            """
            UPDATE guilds 
            SET delete_commands = NOT delete_commands
            WHERE id=$1;
            """, self.id
        )

        self.delete_commands = not self.delete_commands
        return self.delete_commands

    async def toggle_level_up_notifs(self) -> bool:
        await self.db.execute(
            """
            UPDATE guilds 
            SET level_up_notifs_silenced = NOT level_up_notifs_silenced
            WHERE id=$1;
            """, self.id
        )

        self.level_up_notifs_silenced = not self.level_up_notifs_silenced
        return self.level_up_notifs_silenced

    async def get_top_10(self) -> List[MemberDB]:
        top_10 = await self.db.fetch("""SELECT * FROM members WHERE members.guild_id=$1 ORDER BY xp DESC LIMIT 10;""",
                                     self.id)
        return [await MemberDB.get_or_create(bot=self.bot, guild_id=member['guild_id'], member_id=member['user_id'])
                for member in top_10]

    async def set_welcome(self, channel_id: int = None, msg: str = None):
        await self.db.execute(
            """UPDATE guilds SET welcome_channel_id=$1, welcome_message=$2 WHERE id=$3;""",
            channel_id, msg, self.id)

    async def set_bye(self, channel_id: int = None, msg: str = None):
        await self.db.execute(
            """UPDATE guilds SET bye_channel_id=$1, bye_message=$2 WHERE id=$3;""",
            channel_id, msg, self.id)

    async def add_xp_excluded_channel(self, channel_id: int):
        self.xp_excluded_channels.append(channel_id)
        await self.db.execute("UPDATE guilds SET xp_excluded_channels=$1 WHERE id=$2;",
                              self.xp_excluded_channels, self.id)

    async def remove_xp_excluded_channel(self, channel_id: int):
        self.xp_excluded_channels.remove(channel_id)
        await self.db.execute("UPDATE guilds SET xp_excluded_channels=$1 WHERE id=$2;",
                              self.xp_excluded_channels, self.id)

    async def add_assignable_role(self, role_id: int):
        self.assignable_role_ids.append(role_id)
        await self.db.execute(
            """UPDATE guilds SET assignable_role_ids = array_append(assignable_role_ids, $1) WHERE id=$2;""",
            role_id, self.id)

    async def remove_assignable_role(self, role_id: int):
        self.assignable_role_ids.remove(role_id)
        await self.db.execute(
            """UPDATE guilds SET assignable_role_ids = array_remove(assignable_role_ids, $1) WHERE id=$2;""",
            role_id, self.id)

    async def toggle_exclusive_assignable_roles(self):
        status = await self.db.fetchrow(
            """UPDATE guilds 
            SET exclusive_assignable_roles = NOT exclusive_assignable_roles 
            WHERE id=$1 
            RETURNING exclusive_assignable_roles;""",
            self.id)

        self.assignable_roles_are_exclusive = status.get('exclusive_assignable_roles')

    async def set_auto_nsfw(self, type: str = 'hentai', channel_id: int = None, tags: List[str] = None,
                            interval: int = None):
        if type == 'hentai':
            self.auto_hentai_channel_id = channel_id
            self.auto_hentai_tags = tags
            self.auto_hentai_interval = interval
            await self.db.execute(
                """UPDATE guilds SET 
                auto_hentai_channel_id=$1,
                auto_hentai_tags=$2,
                auto_hentai_interval=$3 
                WHERE id=$4;""", channel_id, tags, interval, self.id)
        elif type == 'porn':
            self.auto_porn_channel_id = channel_id
            self.auto_porn_tags = tags
            self.auto_porn_interval = interval
            await self.db.execute(
                """UPDATE guilds SET 
                auto_porn_channel_id=$1,
                auto_porn_tags=$2,
                auto_porn_interval=$3 
                WHERE id=$4;""", channel_id, tags, interval, self.id)
        else:
            raise Exception("Unknown NSFW type!")

    def __eq__(self, other):
        if isinstance(other, GuildDB):
            return self.id == other.id


class GuildLoggingDB(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.modlog_channel_id = data.get('modlog_channel_id')
        self.log_channel_id = data.get('log_channel_id')
        self.simple_mode_is_enabled = data.get('simple_mode')

    @property
    def guild(self) -> discord.Guild:
        return self.bot.get_guild(self.id)

    @property
    def modlog_channel(self) -> discord.TextChannel:
        return self.bot.get_channel(self.modlog_channel_id)

    @property
    def logging_channel(self) -> discord.TextChannel:
        return self.bot.get_channel(self.log_channel_id)

    @property
    def modlog_is_enabled(self):
        return self.modlog_channel is not None

    @property
    def logging_is_enabled(self):
        return self.logging_channel is not None

    @classmethod
    async def get_or_create(cls, bot, guild_id: int):
        logging_db = await bot.db.fetchrow("SELECT * FROM guilds_logging WHERE id=$1;", guild_id)

        if not logging_db:
            try:
                logging_db = await bot.db.fetchrow("INSERT INTO guilds_logging(id) VALUES ($1) RETURNING *;",
                                                   guild_id)
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, guild_id)

        return cls(logging_db, bot)

    async def set_modlog_channel(self, channel_id: int):
        self.modlog_channel_id = channel_id
        await self.db.execute("UPDATE guilds_logging SET modlog_channel_id=$1 WHERE id=$2;",
                              self.modlog_channel_id, self.id)

    async def set_log_channel(self, channel_id: int):
        self.log_channel_id = channel_id
        await self.db.execute("UPDATE guilds_logging SET log_channel_id=$1 WHERE id=$2;",
                              self.log_channel_id, self.id)

    async def change_mode_to_simple(self, mode: bool):
        self.simple_mode_is_enabled = mode
        await self.db.execute("UPDATE guilds_logging SET simple_mode=$1 WHERE id=$2;",
                              self.simple_mode_is_enabled, self.id)


class LoggedMessage(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)
        self.id: int = data.get('message_id')
        self.author_id: int = data.get('author_id')
        self.channel_id: int = data.get('channel_id')
        self.guild_id: int = data.get('guild_id')
        self.content: str = data.get('message_content')
        self.embeds: List[discord.Embed] = [discord.Embed.from_dict(json.loads(x)) for x in data.get('message_embeds')]

    @property
    def guild(self) -> discord.Guild:
        return self.bot.get_guild(self.guild_id)

    @property
    def channel(self) -> discord.TextChannel:
        return self.guild.get_channel(self.channel_id)

    @property
    def author(self) -> discord.User:
        return self.bot.get_user(self.author_id)

    @classmethod
    async def get(cls, bot, message_id: int) -> Optional[LoggedMessage]:
        msg = await bot.db.fetchrow("SELECT * FROM message_log WHERE message_id=$1;", message_id)

        return cls(msg, bot) if msg else None

    @classmethod
    async def get_bulk(cls, bot, message_ids: Union[Set[int], List[int]]) -> List[LoggedMessage]:
        msgs = await bot.db.fetch("SELECT * FROM message_log WHERE message_id=ANY($1);", message_ids)

        return [cls(msg, bot) for msg in msgs]

    @classmethod
    async def insert(cls, bot, message: discord.Message):
        await bot.db.execute(
            """INSERT INTO message_log(message_id, author_id, channel_id, guild_id, message_content, message_embeds, time) 
            VALUES ($1, $2, $3, $4, $5, $6, $7);""",
            message.id, message.author.id, message.channel.id, message.guild.id if message.guild else None,
            message.content, (json.dumps(e.to_dict()) for e in message.embeds),
            message.created_at)  # created_at is UTC, check if we handle this properly

    @classmethod
    async def insert_bulk(cls, bot, messages: List[discord.Message]):
        tup = (
            (message.id, message.author.id, message.channel.id,
             message.guild.id if message.guild else None, message.content,
             tuple(json.dumps(e.to_dict()) for e in message.embeds), message.created_at
             ) for message in messages)

        await bot.db.executemany("""
            INSERT INTO message_log(message_id, author_id, channel_id, guild_id, message_content, message_embeds, time) 
            VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *;
            """, tup)

        # update active guilds with this info
        guild_id_list = list(dict.fromkeys([x.guild.id for x in messages]))
        await GuildDB.update_active_guilds(bot, guild_id_list)

    def jump_url(self):
        return 'https://discord.com/channels/{0}/{1.channel.id}/{1.id}'.format(self.guild_id, self)


class ReminderDB(BaseDBModel):
    class ChannelType(Enum):
        DM = 0
        TEXT_CHANNEL = 1

    def __init__(self, data: Record, bot):
        super(ReminderDB, self).__init__(data, bot)

        self.author_id: int = data.get('author_id')

        self.channel_id: int = data.get('channel_id')
        self.channel_type = self.ChannelType(data.get('channel_type'))

        self.content: str = data.get('content')

        self.time_obj: mido_utils.Time = mido_utils.Time.add_to_previous_date_and_get(
            data.get('creation_date'), data.get('length_in_seconds')
        )

        self.done: bool = data.get('done')

    @classmethod
    async def create(cls,
                     bot,
                     author_id: int,
                     channel_id: int,
                     channel_type: ChannelType,
                     content: str,
                     date_obj: mido_utils.Time):
        created = await bot.db.fetchrow(
            """INSERT INTO 
            reminders(channel_id, channel_type, length_in_seconds, author_id, content) 
            VALUES ($1, $2, $3, $4, $5) RETURNING *;""",
            channel_id, channel_type.value, date_obj.initial_remaining_seconds, author_id, content)

        return cls(created, bot)

    @classmethod
    async def get_uncompleted_reminders(cls, bot, user_id: int = None):
        if user_id is not None:
            reminders = await bot.db.fetch("""SELECT * FROM reminders WHERE author_id=$1 AND done IS NOT TRUE;""",
                                           user_id)
        else:
            reminders = await bot.db.fetch("""SELECT * FROM reminders WHERE done IS NOT TRUE;""")

        return list(sorted((cls(reminder, bot) for reminder in reminders), key=lambda x: x.time_obj.end_date))

    async def complete(self):
        self.done = True
        await self.db.execute("""UPDATE reminders SET done=TRUE WHERE id=$1;""", self.id)

    def __eq__(self, other):
        if isinstance(other, ReminderDB):
            return self.id == other.id


class CustomReaction(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.guild_id: int = data.get('guild_id')
        self.trigger: str = data.get('trigger')
        self.response: str = data.get('response')

        self.delete_trigger: bool = data.get('delete_trigger')
        self.send_in_DM: bool = data.get('send_in_DM')
        self.contains_anywhere: bool = data.get('contains_anywhere')

        self.date_added: mido_utils.Time = mido_utils.Time(data.get('date_added'))
        self.use_count: int = data.get('use_count')

    @classmethod
    async def delete_all(cls, bot, guild_id: int) -> bool:
        await bot.db.execute("DELETE FROM custom_reactions WHERE guild_id=$1;", guild_id)
        return True

    @classmethod
    async def convert(cls, ctx, cr_id: int):  # ctx arg is passed no matter what
        """Converts a Custom Reaction ID argument into local object."""
        try:
            return await CustomReaction.get(bot=ctx.bot, _id=int(cr_id))
        except ValueError:
            raise BadArgument("Please type the ID of the custom reaction, not the name.")

    @classmethod
    async def add(cls, bot, trigger: str, response: str, guild_id=None):
        ret = await bot.db.fetchrow("INSERT INTO custom_reactions(guild_id, trigger, response) "
                                    "VALUES ($1, $2, $3) RETURNING *;",
                                    guild_id, trigger.lower(), response)

        return cls(ret, bot)

    @classmethod
    async def get(cls, bot, _id: int):
        ret = await bot.db.fetchrow("SELECT * FROM custom_reactions WHERE id=$1;", _id)
        if not ret:
            raise mido_utils.NotFoundError(f"No custom reaction found with ID: `{_id}`")

        return cls(ret, bot)

    @classmethod
    async def get_all(cls, bot, guild_id: int = None):
        if guild_id:
            ret = await bot.db.fetch("SELECT * FROM custom_reactions WHERE guild_id=$1;", guild_id)
        else:
            ret = await bot.db.fetch("SELECT * FROM custom_reactions WHERE guild_id IS NULL;")

        return [cls(cr, bot) for cr in ret]

    @classmethod
    async def try_get(cls, bot, msg: str, guild_id):
        msg = msg.strip().lower().replace('%mention%', '')  # remove any manually typed %mention%
        msg = re.sub(f'<@(!?){bot.user.id}>', '%mention%', msg)  # replace actual mention with %mention%

        # guild crs
        ret = await bot.db.fetch("""SELECT * FROM custom_reactions 
        WHERE (trigger = $1
        OR (contains_anywhere=TRUE AND ($1 LIKE concat('%', f_like_escape(trigger), '%')) 
        OR (response LIKE '%\%target\%%' AND $1 LIKE concat(trigger, '%')))
        ) AND guild_id=$2;""", msg, guild_id)

        if not ret:
            # global crs
            ret = await bot.db.fetch("""SELECT * FROM custom_reactions 
            WHERE (
            trigger = $1 
            OR contains_anywhere=TRUE AND ($1 LIKE concat('%', f_like_escape(trigger), '%')) 
            OR (response LIKE '%\%target\%%' AND $1 LIKE concat(trigger, '%'))
            ) AND guild_id IS NULL;""", msg)

            if not ret:
                return None

        return cls(random.choice(ret), bot)

    async def increase_use_count(self):
        self.use_count += 1
        await self.db.execute("UPDATE custom_reactions SET use_count=use_count+1 WHERE id=$1;", self.id)

    async def delete_from_db(self):
        await self.db.execute("DELETE FROM custom_reactions WHERE id=$1;", self.id)

    async def toggle_contains_anywhere(self):
        self.contains_anywhere = not self.contains_anywhere
        await self.db.execute("UPDATE custom_reactions SET contains_anywhere=$1 WHERE id=$2;",
                              self.contains_anywhere, self.id)

    async def toggle_dm(self):
        self.send_in_DM = not self.send_in_DM
        await self.db.execute("""UPDATE custom_reactions SET "send_in_DM"=$1 WHERE id=$2;""",
                              self.send_in_DM, self.id)

    async def toggle_delete_trigger(self):
        self.delete_trigger = not self.delete_trigger
        await self.db.execute("""UPDATE custom_reactions SET delete_trigger=$1 WHERE id=$2;""",
                              self.delete_trigger, self.id)

    def __eq__(self, other):
        if isinstance(other, CustomReaction):
            return self.id == other.id


class CachedImage(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.api_name: str = data.get('api_name')
        self.url: str = data.get('url')
        self.tags: List[str] = data.get('tags')

        self.report_count: int = data.get('report_count')

    @classmethod
    async def get_random(cls,
                         bot,
                         api_names: Union[str, List[str]],
                         limit: int = 1,
                         allow_gif=False) -> List[CachedImage]:
        if isinstance(api_names, str):
            api_names = [api_names]

        if not allow_gif:
            ret = await bot.db.fetch("SELECT * FROM api_cache "
                                     "WHERE api_name = ANY($1) AND is_gif IS FALSE "
                                     "ORDER BY random() LIMIT $2;",
                                     api_names, limit)
        else:
            ret = await bot.db.fetch(
                "SELECT * FROM api_cache "
                "WHERE api_name = ANY($1) "
                "ORDER BY random() LIMIT $2;",
                api_names, limit)

        return [cls(img, bot) for img in ret]

    async def report(self):
        self.report_count += 1
        await self.bot.db.execute("UPDATE api_cache SET report_count = report_count + 1 WHERE id=$1;", self.id)

    @classmethod
    async def get_oldest_checked_images(cls, bot, limit: int = 100) -> List[CachedImage]:
        images = await bot.db.fetch("SELECT * FROM api_cache ORDER BY last_url_check DESC LIMIT $1;", limit)

        return [cls(img, bot) for img in images]

    async def delete(self):
        await self.bot.db.execute("DELETE FROM api_cache WHERE id=$1;", self.id)

    async def url_is_working(self) -> bool:
        try:
            async with self.bot.http_session.get(url=self.url) as response:
                if response.status == 200:
                    await self.url_is_just_checked()
                    return True
                elif response.status == 429:
                    await asyncio.sleep(3.0)
                    return await self.url_is_working()
                elif response.status in (404, 403):
                    return False
                else:
                    raise Exception(f"Unknown status code {response.status} for link: {self.url}")
        except asyncio.TimeoutError:
            return await self.url_is_working()

    async def url_is_just_checked(self):
        await self.bot.db.execute("UPDATE api_cache SET last_url_check=now() WHERE id=$1;", self.id)


class DonutEvent(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.guild_id: int = data.get('guild_id')
        self.channel_id: int = data.get('channel_id')
        self.message_id: int = data.get('message_id')

        self.reward: int = data.get('reward')

        self.end_date: mido_utils.Time = mido_utils.Time(end_date=data.get('end_date'))
        self.attenders: Set[int] = set(data.get('attenders'))

    @classmethod
    async def get(cls,
                  bot,
                  event_id: int = None,
                  guild_id: int = None,
                  channel_id: int = None,
                  message_id: int = None):
        ret = await bot.db.fetch("""SELECT * FROM donut_events 
        WHERE id=$1 OR guild_id=$2 OR channel_id=$3 OR message_id=$4;""", event_id, guild_id, channel_id, message_id)

        return [cls(x, bot) for x in ret]

    @classmethod
    async def get_active_ones(cls, bot) -> List[DonutEvent]:
        ret = await bot.db.fetch("SELECT * FROM donut_events;")
        objects = [cls(x, bot) for x in ret]

        return list(x for x in objects if x.end_date.end_date_has_passed is False)

    @classmethod
    async def create(cls,
                     bot,
                     reward: int,
                     guild_id: int,
                     channel_id: int,
                     message_id: int,
                     length: mido_utils.Time):
        ret = await bot.db.fetchrow(
            """INSERT INTO donut_events(reward, guild_id, channel_id, message_id, end_date) 
            VALUES ($1, $2, $3, $4, $5) RETURNING  *;""",
            reward, guild_id, channel_id, message_id, length.end_date)

        return cls(ret, bot)

    async def add_attender(self, attender_id: int):
        self.attenders.add(attender_id)
        await self.db.execute("UPDATE donut_events SET attenders=array_append(attenders, $1) WHERE id=$2;",
                              attender_id, self.id)

    def user_is_eligible(self, user):
        return user.bot is False and user.id not in self.attenders

    async def reward_attender(self, attender_id: int, user_db_obj: UserDB = None):
        await self.add_attender(attender_id)

        user_db = user_db_obj or await UserDB.get_or_create(bot=self.bot, user_id=attender_id)
        await user_db.add_cash(amount=self.reward, reason="Attended a donut event.")

        self.bot.logger.info(
            f"User {user_db.discord_name} has been awarded {self.reward} donuts for reacting to the donut event."
        )

        from mido_utils.converters import readable_currency
        e = mido_utils.Embed(bot=self.bot,
                             description=f"You have been awarded **{readable_currency(self.reward)}** "
                                         f"for attending the donut event!")
        try:
            await user_db.discord_obj.send(embed=e)
        except discord.Forbidden:
            pass

    def __eq__(self, other):
        if isinstance(other, DonutEvent):
            return self.id == other.id


class TransactionLog(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.user_id: int = data.get('user_id')
        self.amount: int = data.get('amount')
        self.reason: str = data.get('reason')
        self.date: mido_utils.Time = mido_utils.Time(start_date=data.get('date'))

    @classmethod
    async def get_users_logs(cls, bot, user_id: int) -> List[TransactionLog]:
        ret = await bot.db.fetch("SELECT * FROM transaction_history WHERE user_id=$1 ORDER BY date DESC;", user_id)

        return [cls(x, bot) for x in ret]


class BlacklistDB(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.type: str = data.get('type')
        self.reason: str = data.get('reason')
        self.date = mido_utils.Time(data.get('date'))

    @classmethod
    async def get(cls, bot, user_or_guild_id: int, type: str):
        ret = await bot.db.fetchrow("SELECT * FROM blacklist WHERE user_or_guild_id=$1 AND type=$2;",
                                    user_or_guild_id, type)
        if not ret:
            return None
        else:
            return cls(ret, bot)

    @classmethod
    async def blacklist(cls,
                        bot,
                        user_or_guild_id: int,
                        type: str = 'user',
                        reason: str = None):
        ret = await bot.db.fetchrow(
            "INSERT INTO blacklist(user_or_guild_id, type, reason) VALUES ($1, $2, $3) RETURNING *;",
            user_or_guild_id, type, reason
        )

        return cls(ret, bot)

    @classmethod
    async def unblacklist(cls,
                          bot,
                          user_or_guild_id: int,
                          type: str = 'user'):

        return await bot.db.execute(
            "DELETE FROM blacklist WHERE user_or_guild_id=$1 AND type=$2;",
            user_or_guild_id, type
        )


class XpRoleReward(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.guild_id = data.get('guild_id')
        self.level = data.get('level')
        self.role_id = data.get('role_id')

    @classmethod
    async def create(cls, bot, guild_id: int, level: int, role_id: int) -> XpRoleReward:
        ret = await bot.db.fetchrow(
            """INSERT INTO guilds_xp_role_rewards(guild_id, level, role_id) 
            VALUES($1, $2, $3) RETURNING *;""", guild_id, level, role_id)
        return cls(ret, bot)

    @classmethod
    async def get_level_reward(cls, bot, guild_id: int, level: int) -> Optional[XpRoleReward]:
        ret = await bot.db.fetchrow("SELECT * FROM guilds_xp_role_rewards WHERE guild_id=$1 AND level=$2;",
                                    guild_id, level)
        if ret:
            return cls(ret, bot)
        else:
            return None

    @classmethod
    async def get_all(cls, bot, guild_id) -> List[XpRoleReward]:
        ret = await bot.db.fetch("SELECT * FROM guilds_xp_role_rewards WHERE guild_id=$1;", guild_id)
        return [cls(reward, bot) for reward in ret]

    async def set_role_reward(self, role_id):
        self.role_id = role_id
        await self.db.execute("UPDATE guilds_xp_role_rewards SET role_id=$1 WHERE guild_id=$2 AND level=$3;",
                              self.role_id, self.guild_id, self.level)

    async def delete(self):
        await self.db.execute("DELETE FROM guilds_xp_role_rewards WHERE guild_id=$1 AND level=$2;",
                              self.guild_id, self.level)


class HangmanWord(BaseDBModel):
    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.word = data.get('word')
        self.category = data.get('category')

    def __repr__(self):
        return self.word

    @classmethod
    async def get_categories_and_counts(cls, bot) -> Dict[str, int]:
        ret = await bot.db.fetch("SELECT category, count(category) AS count FROM hangman_words GROUP BY category;")
        return {category: count for category, count in ret}

    @classmethod
    async def add_word(cls, bot, category: str, word: str):
        ret = await bot.db.fetchrow("INSERT INTO hangman_words(category, word) VALUES ($1, $2) RETURNING *;",
                                    category, word)
        return cls(ret, bot)

    @classmethod
    async def get_random_word(cls, bot, category: str):
        ret = await bot.db.fetchrow("SELECT * FROM hangman_words WHERE category = $1 ORDER BY random() LIMIT 1;",
                                    category)
        return cls(ret, bot)
