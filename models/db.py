from __future__ import annotations

import asyncio
import json
import random
import re
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Union

import aiohttp
import asyncpg
import discord
from asyncpg import Record
from discord.ext.commands import BadArgument

import mido_utils
import models

# TODO: possibly rewrite this

__all__ = ['XpAnnouncement', 'NSFWImage',  # these 2 are not actual tables
           'ModLog', 'UserDB', 'MemberDB',
           'GuildDB', 'GuildLoggingDB', 'GuildNSFWDB',
           'LoggedMessage', 'ReminderDB', 'CustomReaction',
           'CachedImage', 'DonutEvent', 'TransactionLog',
           'BlacklistDB', 'XpRoleReward', 'HangmanWord', 'RepeatDB']


async def run_create_table_funcs(db):
    # we are not able to do isinstance(_class, BaseDBModel) due to importlib.reload bugs
    # so skip first 2 manually
    for class_name in __all__[2:]:
        _class = globals()[class_name]
        await _class.create_table(db)


class XpAnnouncement(Enum):
    SILENT = 0
    DM = 1
    GUILD = 2


class BaseDBModel:
    TABLE_DEFINITION = None

    def __init__(self, data: Record, bot):
        self.bot = bot
        self.db = self.bot.db

        self.data = data

        self.id = data.get('id')

        self.date_added = data.get('date_added')

    @classmethod
    async def create_table(cls, bot):
        if cls.TABLE_DEFINITION is None:
            raise NotImplemented

        bot.logger.debug(f"Creating database table for class {cls.__name__}.")
        await bot.db.execute(cls.TABLE_DEFINITION)

    def __eq__(self, other):
        raise NotImplemented


class ModLog(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS modlogs
(
    id                serial
        CONSTRAINT modlogs_pkey
            PRIMARY KEY,
    guild_id          bigint                                 NOT NULL,
    user_id           bigint                                 NOT NULL,
    type              smallint                               NOT NULL,
    reason            text,
    executor_id       bigint,
    length_in_seconds bigint,
    date              timestamp WITH TIME ZONE DEFAULT NOW() NOT NULL,
    done              boolean,
    hidden            boolean                  DEFAULT FALSE NOT NULL
);
"""

    class Type(Enum):
        MUTE = 0
        UNMUTE = 1
        KICK = 1
        BAN = 2
        UNBAN = 3

    def __init__(self, modlog_db: Record, bot):
        super().__init__(modlog_db, bot)

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
                AND done IS NOT TRUE
                AND guild_id=ANY($2);""", (ModLog.Type.MUTE.value, ModLog.Type.BAN.value), [x.id for x in bot.guilds])

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


class UserDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS users
(
    id                        bigint                                            NOT NULL
        CONSTRAINT users_pkey
            PRIMARY KEY,
    cash                      bigint                   DEFAULT 0                NOT NULL,
    eaten_cash                bigint                   DEFAULT 0                NOT NULL,
    last_daily_claim          timestamp WITH TIME ZONE,
    xp                        bigint                   DEFAULT 0                NOT NULL,
    last_xp_gain              timestamp WITH TIME ZONE,
    level_up_notification     smallint                 DEFAULT 0                NOT NULL,
    waifu_affinity_id         bigint,
    waifu_claimer_id          bigint,
    waifu_price               bigint,
    waifu_affinity_changes    smallint                 DEFAULT 0                NOT NULL,
    waifu_divorce_count       smallint                 DEFAULT 0                NOT NULL,
    waifu_items               smallint[]               DEFAULT '{}'::smallint[] NOT NULL,
    name_and_discriminator    text,
    date_added                timestamp WITH TIME ZONE DEFAULT NOW(),
    last_patreon_claim_date   timestamp WITH TIME ZONE,
    last_patreon_claim_amount bigint
);

CREATE INDEX IF NOT EXISTS user_xp_leaderboard_index
    ON users (xp DESC);
"""

    def __init__(self, user_db: Record, bot):
        super().__init__(user_db, bot)

        self.cash: int = user_db.get('cash')
        self.eaten_cash: int = user_db.get('eaten_cash')

        self._discord_name = user_db.get('name_and_discriminator') or self.id

        self.level_up_notification = XpAnnouncement(user_db.get('level_up_notification'))
        self.total_xp: int = user_db.get('xp')
        self.xp_status = mido_utils.Time.add_to_previous_date_and_get(
            user_db.get('last_xp_gain'), bot.config.cooldowns['xp']
        )

        self.daily_date_status = mido_utils.Time.add_to_previous_date_and_get(user_db.get('last_daily_claim'),
                                                                              bot.config.cooldowns['daily'])
        self.waifu = models.Waifu(self)

        # patreon claim
        self.last_patreon_claim_date = mido_utils.Time.add_to_previous_date_and_get(
            previous_date=user_db.get('last_patreon_claim_date'),
            seconds=60 * 60 * 24 * 30)  # 1 month
        self.last_patreon_claim_amount: int = user_db.get('last_patreon_claim_amount', 0)

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
    async def get_or_create(cls, bot, user_id: int) -> UserDB:
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
    def cash_str(self) -> str:
        return mido_utils.readable_currency(self.cash)

    @property
    def cash_str_without_emoji(self) -> str:
        return mido_utils.readable_bigint(self.cash)

    @property
    def eaten_cash_str(self) -> str:
        return mido_utils.readable_currency(self.eaten_cash)

    @property
    def eaten_cash_str_without_emoji(self) -> str:
        return mido_utils.readable_bigint(self.eaten_cash)

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

    async def eat_cash(self, amount: int):
        await self.remove_cash(amount, reason='Ate it.')

        self.eaten_cash += amount

        await self.db.execute("UPDATE users SET eaten_cash=$1 WHERE id=$2;", self.eaten_cash, self.id)

    async def get_eaten_cash_rank(self) -> int:
        result = await self.db.fetchrow("""
            SELECT COUNT(*) FROM users
            WHERE users.eaten_cash >= $1;
            """, self.eaten_cash)

        return result['count']

    @classmethod
    async def get_top_cash_eaten_people(cls, bot, limit: int = 10) -> List[UserDB]:
        top = await bot.db.fetch("""SELECT * FROM users ORDER BY eaten_cash DESC LIMIT $1;""", limit)
        return [UserDB(user, bot) for user in top]

    async def add_xp(self, amount: int, owner=False):
        if not self.xp_status.end_date_has_passed and not owner:
            raise mido_utils.OnCooldownError(
                f"User {self.discord_name} [{self.id}] "
                f"still needs **{self.xp_status.remaining_string}** to be able to gain XP.")

        self.total_xp += amount
        await self.db.execute(
            """UPDATE users SET xp = $1, last_xp_gain = $2 WHERE id=$3""",
            self.total_xp, datetime.now(timezone.utc), self.id)

    async def remove_xp(self, amount: int) -> int:
        await self.db.execute(
            """UPDATE users SET xp = xp - $1 WHERE id=$2""",
            amount, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self.db.fetchrow("""
            SELECT COUNT(*) FROM users
            WHERE users.xp >= $1;
            """, self.total_xp)

        return result['count']

    @classmethod
    async def get_top_xp_people(cls, bot, limit: int = 10) -> List[UserDB]:
        top = await bot.db.fetch("""SELECT * FROM users ORDER BY xp DESC LIMIT $1;""", limit)
        return [UserDB(user, bot) for user in top]

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

    async def claim_patreon_reward(self, patron_obj: models.UserAndPledgerCombined):
        amount_to_give = patron_obj.level_status.monthly_donut_reward
        if not self.last_patreon_claim_date.end_date_has_passed:
            if self.last_patreon_claim_amount < patron_obj.level_status.monthly_donut_reward:
                amount_to_give = patron_obj.level_status.monthly_donut_reward - self.last_patreon_claim_amount
            else:
                raise mido_utils.CantClaimRightNow(f"You're on cooldown. Increase your pledge to get more rewards "
                                                   f"or wait **{self.last_patreon_claim_date.remaining_string}**.")

        await self.db.execute("UPDATE users SET last_patreon_claim_date=$1, last_patreon_claim_amount=$2 WHERE id=$3;",
                              datetime.now(timezone.utc), patron_obj.level_status.monthly_donut_reward, self.id)
        await self.add_cash(amount=amount_to_give, reason='Claimed Patreon reward.')

    def __eq__(self, other):
        if isinstance(other, UserDB):
            return self.id == other.id


class MemberDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS members
(
    guild_id     bigint                             NOT NULL,
    user_id      bigint                             NOT NULL,
    xp           bigint                   DEFAULT 0 NOT NULL,
    last_xp_gain timestamp WITH TIME ZONE,
    date_added   timestamp WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT pkey
        PRIMARY KEY (guild_id, user_id)
);

CREATE INDEX IF NOT EXISTS member_xp_leaderboard_index
    ON members (xp DESC, guild_id ASC);
"""

    # noinspection PyTypeChecker
    def __init__(self, member_db: Record, bot):
        super().__init__(member_db, bot)

        self.id = member_db.get('user_id')

        self.guild: GuildDB = None
        self.user: UserDB = None

        self.total_xp: int = member_db.get('xp')

        self.xp_status = mido_utils.Time.add_to_previous_date_and_get(
            member_db.get('last_xp_gain'), bot.config.cooldowns['xp'])

    @property
    def discord_name(self):
        return self.user.discord_name

    @classmethod
    async def get_or_create(cls, bot, guild_id: int, member_id: int) -> MemberDB:
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

    async def add_xp(self, amount: int, owner: bool = False):
        if not self.xp_status.end_date_has_passed and not owner:
            raise mido_utils.OnCooldownError(
                f"User {self.discord_name} [{self.id}] "
                f"still needs **{self.xp_status.remaining_string}** to be able to gain XP.")

        self.total_xp += amount
        await self.db.execute(
            """UPDATE members SET xp = $1, last_xp_gain = $2 WHERE guild_id=$3 AND user_id=$4""",
            self.total_xp, datetime.now(timezone.utc), self.guild.id, self.id)

    async def remove_xp(self, amount: int) -> int:
        await self.db.execute(
            """UPDATE members SET xp = xp - $1 WHERE guild_id=$2 AND user_id=$3;""",
            amount, self.guild.id, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self.db.fetchrow("""
            SELECT COUNT(*) FROM members 
            WHERE guild_id=$1 
            AND members.xp >= $2;
            """, self.guild.id, self.total_xp)

        return result['count']

    def __eq__(self, other):
        if isinstance(other, MemberDB):
            return self.id == other.id


class GuildNSFWDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS guilds_nsfw_settings
(
    id                     bigint NOT NULL
        CONSTRAINT guilds_nsfw_settings_pk
            PRIMARY KEY,
    auto_hentai_channel_id bigint,
    auto_hentai_tags       text[],
    auto_hentai_interval   integer,
    auto_porn_channel_id   bigint,
    auto_porn_tags         text[],
    auto_porn_interval     integer,
    blacklisted_tags       text[] DEFAULT '{}'::text[]
);
"""

    def __init__(self, nsfw_db: Record, bot):
        super().__init__(nsfw_db, bot)

        self.blacklisted_tags: List[str] = [tag.replace(' ', '_') for tag in nsfw_db.get('blacklisted_tags', [])]

        # auto hentai
        self.auto_hentai_channel_id: int = nsfw_db.get('auto_hentai_channel_id')
        self.auto_hentai_tags: List[str] = nsfw_db.get('auto_hentai_tags')
        self.auto_hentai_interval: int = nsfw_db.get('auto_hentai_interval')

        # auto porn
        self.auto_porn_channel_id: int = nsfw_db.get('auto_porn_channel_id')
        self.auto_porn_tags: List[str] = nsfw_db.get('auto_porn_tags')
        self.auto_porn_interval: int = nsfw_db.get('auto_porn_interval')

    def get_auto_nsfw_properties(self, nsfw_type: NSFWImage.Type) -> Tuple[int, List[str], int]:
        if nsfw_type is NSFWImage.Type.hentai:
            return self.auto_hentai_channel_id, self.auto_hentai_tags, self.auto_hentai_interval
        elif nsfw_type is NSFWImage.Type.porn:
            return self.auto_porn_channel_id, self.auto_porn_tags, self.auto_porn_interval
        else:
            raise mido_utils.UnknownNSFWType(nsfw_type)

    async def blacklist_tag(self, tag: str):
        self.blacklisted_tags.append(tag.lower())

        await self.bot.db.execute("UPDATE guilds_nsfw_settings "
                                  "SET blacklisted_tags=ARRAY_APPEND(blacklisted_tags, $1) WHERE id=$2;",
                                  tag.lower(), self.id)

    async def whitelist_tag(self, tag: str):
        self.blacklisted_tags.remove(tag.lower())

        await self.bot.db.execute("UPDATE guilds_nsfw_settings "
                                  "SET blacklisted_tags=ARRAY_REMOVE(blacklisted_tags, $1) WHERE id=$2;",
                                  tag.lower(), self.id)

    async def set_auto_nsfw(self, nsfw_type: NSFWImage.Type, channel_id: int = None, tags: List[str] = None,
                            interval: int = None):
        if nsfw_type is NSFWImage.Type.hentai:
            self.auto_hentai_channel_id = channel_id
            self.auto_hentai_tags = tags
            self.auto_hentai_interval = interval
            await self.db.execute(
                """UPDATE guilds_nsfw_settings SET 
                auto_hentai_channel_id=$1,
                auto_hentai_tags=$2,
                auto_hentai_interval=$3 
                WHERE id=$4;""", channel_id, tags, interval, self.id)
        elif nsfw_type is NSFWImage.Type.porn:
            self.auto_porn_channel_id = channel_id
            self.auto_porn_tags = tags
            self.auto_porn_interval = interval
            await self.db.execute(
                """UPDATE guilds_nsfw_settings SET 
                auto_porn_channel_id=$1,
                auto_porn_tags=$2,
                auto_porn_interval=$3 
                WHERE id=$4;""", channel_id, tags, interval, self.id)
        else:
            raise mido_utils.UnknownNSFWType(nsfw_type)

    @classmethod
    async def get_or_create(cls, bot, guild_id: int) -> GuildNSFWDB:
        nsfw_db = await bot.db.fetchrow("""SELECT * FROM guilds_nsfw_settings WHERE id=$1;""", guild_id)
        if not nsfw_db:
            try:
                nsfw_db = await bot.db.fetchrow(
                    """INSERT INTO guilds_nsfw_settings(id) VALUES ($1) RETURNING *;""",
                    guild_id)
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, guild_id)

        return cls(nsfw_db, bot)

    @classmethod
    async def get_auto_nsfw_guilds(cls, bot):
        ret = await bot.db.fetch("SELECT * FROM guilds_nsfw_settings "
                                 "WHERE (auto_hentai_channel_id IS NOT NULL "
                                 "OR auto_porn_channel_id IS NOT NULL) "
                                 "AND id=ANY($1);", [x.id for x in bot.guilds]  # clustering
                                 )
        return [cls(guild, bot) for guild in ret]


class GuildDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS guilds
(
    id                         bigint                                          NOT NULL
        CONSTRAINT guilds_pk
            PRIMARY KEY,
    prefix                     text                     DEFAULT 's.'::text,
    delete_commands            boolean                  DEFAULT FALSE,
    level_up_notifs_silenced   boolean                  DEFAULT FALSE,
    volume                     smallint                 DEFAULT 15             NOT NULL,
    welcome_channel_id         bigint,
    welcome_message            text,
    bye_channel_id             bigint,
    bye_message                text,
    assignable_role_ids        bigint[]                 DEFAULT '{}'::bigint[] NOT NULL,
    exclusive_assignable_roles boolean                  DEFAULT FALSE          NOT NULL,
    welcome_delete_after       integer                  DEFAULT 0              NOT NULL,
    bye_delete_after           integer                  DEFAULT 0              NOT NULL,
    date_added                 timestamp WITH TIME ZONE DEFAULT NOW(),
    last_message_date          timestamp WITH TIME ZONE DEFAULT NOW(),
    xp_excluded_channels       bigint[]                 DEFAULT '{}'::bigint[],
    welcome_role_id            bigint
);
"""

    def __init__(self, guild_db: Record, bot):
        super().__init__(guild_db, bot)

        self.prefix: str = guild_db.get('prefix')

        self.delete_commands: bool = guild_db.get('delete_commands')
        self.level_up_notifs_silenced: bool = guild_db.get('level_up_notifs_silenced')
        self.last_message_date: mido_utils.Time = mido_utils.Time(guild_db.get('last_message_date'))
        self.xp_excluded_channels: List[int] = guild_db.get('xp_excluded_channels')

        # welcome
        self.welcome_role_id: int = guild_db.get('welcome_role_id')

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

    @classmethod
    async def get_guilds_that_are_active_in_last_x_hours(cls, bot, hours: int = 24):
        ret = await bot.db.fetch("SELECT * FROM guilds WHERE last_message_date > (NOW() - $1::interval) "
                                 "AND id=ANY($2);",  # clustering
                                 timedelta(hours=hours), [x.id for x in bot.guilds])

        return [cls(guild, bot) for guild in ret]

    @staticmethod
    async def update_active_guilds(bot, guild_id_list: List[int]):
        await bot.db.execute("UPDATE guilds SET last_message_date=NOW() WHERE id=ANY($1);", guild_id_list)

    @classmethod
    async def get_or_create(cls, bot, guild_id: int) -> GuildDB:
        guild_db = await bot.db.fetchrow("""SELECT * FROM guilds WHERE id=$1;""", guild_id)
        if not guild_db:
            try:
                guild_db = await bot.db.fetchrow(
                    """INSERT INTO guilds(id, prefix) VALUES ($1, $2) RETURNING *;""",
                    guild_id, bot.config.default_prefix)
            except asyncpg.UniqueViolationError:
                return await cls.get_or_create(bot, guild_id)

        return cls(guild_db, bot)

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

    async def get_top_xp_people(self, limit: int = 10) -> List[MemberDB]:
        top = await self.db.fetch("""SELECT * FROM members WHERE members.guild_id=$1 ORDER BY xp DESC LIMIT $2;""",
                                  self.id, limit)
        return [await MemberDB.get_or_create(bot=self.bot, guild_id=member['guild_id'], member_id=member['user_id'])
                for member in top]

    async def set_welcome_role(self, role_id: int = None):
        self.welcome_role_id = role_id
        await self.db.execute(
            """UPDATE guilds SET welcome_role_id=$1 WHERE id=$2;""",
            role_id, self.id)

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
            """UPDATE guilds SET assignable_role_ids = ARRAY_APPEND(assignable_role_ids, $1) WHERE id=$2;""",
            role_id, self.id)

    async def remove_assignable_role(self, role_id: int):
        self.assignable_role_ids.remove(role_id)
        await self.db.execute(
            """UPDATE guilds SET assignable_role_ids = ARRAY_REMOVE(assignable_role_ids, $1) WHERE id=$2;""",
            role_id, self.id)

    async def toggle_exclusive_assignable_roles(self):
        status = await self.db.fetchrow(
            """UPDATE guilds 
            SET exclusive_assignable_roles = NOT exclusive_assignable_roles 
            WHERE id=$1 
            RETURNING exclusive_assignable_roles;""",
            self.id)

        self.assignable_roles_are_exclusive = status.get('exclusive_assignable_roles')

    def __eq__(self, other):
        if isinstance(other, GuildDB):
            return self.id == other.id


class GuildLoggingDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS guilds_logging
(
    id                bigint,
    modlog_channel_id bigint,
    log_channel_id    bigint,
    simple_mode       boolean
);
"""

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

    async def set_log_channel(self, channel_id: Optional[int]):
        self.log_channel_id = channel_id
        await self.db.execute("UPDATE guilds_logging SET log_channel_id=$1 WHERE id=$2;",
                              self.log_channel_id, self.id)

    async def change_mode_to_simple(self, mode: bool):
        self.simple_mode_is_enabled = mode
        await self.db.execute("UPDATE guilds_logging SET simple_mode=$1 WHERE id=$2;",
                              self.simple_mode_is_enabled, self.id)


class LoggedMessage(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS message_log
(
    message_id      bigint                                 NOT NULL
        CONSTRAINT message_log_pk
            PRIMARY KEY,
    author_id       bigint                                 NOT NULL,
    channel_id      bigint                                 NOT NULL,
    guild_id        bigint,
    message_content text                                   NOT NULL,
    message_embeds  text[]                   DEFAULT '{}'::text[],
    created_at      timestamp WITH TIME ZONE DEFAULT NOW() NOT NULL
);
"""

    class UnknownUser:
        def __init__(self):
            self.id = 0
            self.mention = '__UNKNOWN__'
            self.avatar_url = 'https://cdn.discordapp.com/embed/avatars/0.png'

        def __str__(self):
            return '**UNKNOWN**'

    def __init__(self, data: Union[Record, dict], bot):
        super().__init__(data, bot)
        self.id: int = data.get('message_id')

        self.author_id: int = data.get('author_id')
        self.channel_id: int = data.get('channel_id')
        self.guild_id: int = data.get('guild_id')

        self.content: str = data.get('message_content') or '**UNKNOWN**'

        self.embeds: List[discord.Embed] = [discord.Embed.from_dict(json.loads(x))
                                            for x in data.get('message_embeds', [])]

        self.created_at: datetime = data.get('created_at') or datetime(1970, 1, 1, tzinfo=timezone.utc)

    @property
    def guild(self) -> discord.Guild:
        return self.bot.get_guild(self.guild_id)

    @property
    def channel(self) -> discord.TextChannel:
        return self.guild.get_channel(self.channel_id)

    @property
    def author(self) -> Union[discord.Member, LoggedMessage.UnknownUser]:
        return self.guild.get_member(self.author_id) or self.UnknownUser()

    @property
    def jump_url(self):
        return 'https://discord.com/channels/{0}/{1.channel.id}/{1.id}'.format(self.guild_id, self)

    @classmethod
    def _uncached_msg_obj(cls, bot, guild_id: int, channel_id: int, message_id: int) -> LoggedMessage:
        return cls(
            {'guild_id': guild_id, 'channel_id': channel_id, 'message_id': message_id},
            bot)

    @classmethod
    async def get(cls, bot, guild_id: int, channel_id: int, message_id: int) -> LoggedMessage:
        msg = await bot.db.fetchrow("SELECT * FROM message_log WHERE message_id=$1;", message_id)

        return cls(msg, bot) if msg else cls._uncached_msg_obj(bot, guild_id, channel_id, message_id)

    @classmethod
    async def get_bulk(cls, bot, guild_id: int, channel_id: int,
                       message_ids: Union[Set[int], List[int]]) -> List[LoggedMessage]:
        ret = []

        msgs = await bot.db.fetch("SELECT * FROM message_log WHERE message_id=ANY($1);", message_ids)

        # append uncached message objects to the ret list
        cached_id_list = [msg.get('message_id') for msg in msgs]
        for msg_id in message_ids:
            if msg_id not in cached_id_list:
                ret.append(cls._uncached_msg_obj(bot, guild_id, channel_id, msg_id))

        # append cached messages
        ret.extend([cls(msg, bot) for msg in msgs])

        return ret

    @classmethod
    async def insert(cls, bot, message: discord.Message):
        await cls.insert_bulk(bot, [message])

    @classmethod
    async def insert_bulk(cls, bot, messages: List[discord.Message]):
        tup = (
            (message.id,
             message.author.id,
             message.channel.id,
             message.guild.id if message.guild else None,
             message.content.replace("\u0000", ""),
             tuple(json.dumps(e.to_dict()) for e in message.embeds),
             message.created_at
             ) for message in messages)

        await bot.db.executemany("""
             INSERT INTO message_log(
             message_id, 
             author_id, 
             channel_id, 
             guild_id, 
             message_content, 
             message_embeds, 
             created_at) 
             VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT DO NOTHING;
            """, tup)

        # update active guilds with this info
        guild_id_list = list(dict.fromkeys([x.guild.id for x in messages if x.guild]))
        await GuildDB.update_active_guilds(bot, guild_id_list)

    @classmethod
    async def delete_old_messages(cls, bot):
        # delete messages that are older than 7 days
        await bot.db.execute("DELETE FROM message_log WHERE created_at < (NOW() - INTERVAL '7 days')")


class ReminderDB(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS reminders
(
    id                serial
        CONSTRAINT reminders_pk
            PRIMARY KEY,
    author_id         bigint                                 NOT NULL,
    channel_id        bigint                                 NOT NULL,
    channel_type      smallint                 DEFAULT 0     NOT NULL,
    content           text                                   NOT NULL,
    length_in_seconds bigint                                 NOT NULL,
    creation_date     timestamp WITH TIME ZONE DEFAULT NOW() NOT NULL,
    done              boolean                  DEFAULT FALSE NOT NULL
);

"""

    class ChannelType(Enum):
        DM = 0
        TEXT_CHANNEL = 1

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

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
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS custom_reactions
(
    id                serial
        CONSTRAINT custom_reactions_pk
            PRIMARY KEY,
    guild_id          bigint,
    trigger           text                                   NOT NULL,
    response          text                                   NOT NULL,
    date_added        timestamp WITH TIME ZONE DEFAULT NOW(),
    delete_trigger    boolean                  DEFAULT FALSE NOT NULL,
    "send_in_DM"      boolean                  DEFAULT FALSE NOT NULL,
    contains_anywhere boolean                  DEFAULT FALSE NOT NULL,
    use_count         integer                  DEFAULT 0     NOT NULL
);
"""

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
        OR (contains_anywhere=TRUE AND ($1 LIKE CONCAT('%', f_like_escape(trigger), '%')) 
        OR (response LIKE '%\%target\%%' AND $1 LIKE CONCAT(trigger, '%')))
        ) AND guild_id=$2;""", msg, guild_id)

        if not ret:
            # global crs
            ret = await bot.db.fetch("""SELECT * FROM custom_reactions 
            WHERE (
            trigger = $1 
            OR contains_anywhere=TRUE AND ($1 LIKE CONCAT('%', f_like_escape(trigger), '%')) 
            OR (response LIKE '%\%target\%%' AND $1 LIKE CONCAT(trigger, '%'))
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


class NSFWImage:
    SEPARATOR = '|;^'

    EMBED_PREVIEW_FORMATS = ('png', 'jpg', 'jpeg', 'gif', 'gifv')

    class Type(Enum):
        porn = auto()
        hentai = auto()

    def __init__(self, url: str, tags: List[str] = None, api_name: str = None):
        self.url = url
        self.tags = tags or []
        self.api_name = api_name

    @property
    def cache_value(self) -> str:
        # TODO: maybe give up on detailed cache value to save processing power?
        return self.url \
               + NSFWImage.SEPARATOR \
               + '+'.join(tag for tag in self.tags if tag) \
               + NSFWImage.SEPARATOR \
               + self.api_name

    @classmethod
    def convert_from_cache(cls, value: str) -> NSFWImage:
        if isinstance(value, tuple):
            value = value[0]

        url, tags, api_name = value.split(NSFWImage.SEPARATOR)

        if isinstance(tags, tuple):
            tags = tags[0]

        return cls(url, tags.split('+'), api_name)

    @property
    def readable_tags(self):
        return ", ".join(self.tags).replace("_", " ")

    def get_embed(self, bot) -> mido_utils.Embed:
        e = mido_utils.Embed(bot=bot,
                             description=f"Image not working? [Click here.]({self.url})",
                             image_url=self.url)

        stuff_to_add_to_footer = []
        if self.api_name:
            stuff_to_add_to_footer.append(f"API: {self.api_name}")
        if self.tags:
            stuff_to_add_to_footer.append(f"Tags: {self.readable_tags[:2000]}")

        if stuff_to_add_to_footer:
            e.set_footer(text=' | '.join(stuff_to_add_to_footer))

        return e

    def get_send_kwargs(self, bot) -> dict:
        should_send_as_embed = False
        for _format in self.EMBED_PREVIEW_FORMATS:
            if self.url.endswith(_format):
                should_send_as_embed = True
                break

        if should_send_as_embed:
            return {'embed': self.get_embed(bot)}
        else:
            return {'content': self.url}


class CachedImage(BaseDBModel, NSFWImage):
    """uses the api_cache table"""
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS api_cache
(
    id             bigserial
        CONSTRAINT api_cache_pk
            PRIMARY KEY,
    api_name       text                         NOT NULL,
    url            text                         NOT NULL,
    tags           text[]  DEFAULT '{}'::text[] NOT NULL,
    report_count   integer DEFAULT 0,
    is_gif         boolean DEFAULT FALSE,
    last_url_check timestamp WITH TIME ZONE
);

CREATE UNIQUE INDEX IF NOT EXISTS api_cache_url_uindex
    ON api_cache (url);"""

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.url: str = data.get('url')
        self.tags: List[str] = data.get('tags', [])
        # self.api_name: str = data.get('api_name')
        self.api_name: str = 'Shinobu NSFW API'

        self.report_count: int = data.get('report_count')

    @classmethod
    async def get_random(cls,
                         bot,
                         subreddits: List[models.LocalSubreddit],
                         limit: int = 1,
                         allow_gif=False) -> List[CachedImage]:
        if not allow_gif:
            ret = await bot.db.fetch("SELECT * FROM api_cache "
                                     "WHERE api_name = ANY($1) AND is_gif IS FALSE "
                                     "ORDER BY RANDOM() LIMIT $2;",
                                     [x.db_name for x in subreddits], limit)
        else:
            ret = await bot.db.fetch(
                "SELECT * FROM api_cache "
                "WHERE api_name = ANY($1) "
                "ORDER BY RANDOM() LIMIT $2;",
                [x.db_name for x in subreddits], limit)

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

    async def url_is_working(self) -> Optional[bool]:
        self.bot.logger.debug(f"Checking image: {self.url}")
        try:
            async with self.bot.http_session.get(url=self.url) as response:
                if response.status == 200:
                    await self.url_is_just_checked()
                    return True
                elif response.status in (400, 409, 429) or response.status >= 500:
                    # if we are rate limited or the target server is dying, return None to try again later
                    # 400 is an indication of bad request but how could be a simple get check
                    # to a public image is a bad request? we ignore those too
                    return None
                elif response.status in (404, 403):
                    return False
                else:
                    raise Exception(f"Unknown status code {response.status} for link: {self.url}")
        except (asyncio.TimeoutError, aiohttp.ClientOSError):
            return None
        except aiohttp.ClientConnectorError:
            return False

    async def url_is_just_checked(self):
        await self.bot.db.execute("UPDATE api_cache SET last_url_check=NOW() WHERE id=$1;", self.id)


class DonutEvent(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS donut_events
(
    id                 serial
        CONSTRAINT donut_events_pk
            PRIMARY KEY,
    guild_id           bigint                          NOT NULL,
    channel_id         bigint                          NOT NULL,
    message_id         bigint                          NOT NULL,
    end_date           timestamp WITH TIME ZONE        NOT NULL,
    attenders          bigint[] DEFAULT '{}'::bigint[] NOT NULL,
    reward             integer  DEFAULT 1              NOT NULL,
    start_date         timestamp WITH TIME ZONE,
    message_is_deleted boolean  DEFAULT FALSE          NOT NULL
);
"""

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.guild_id: int = data.get('guild_id')
        self.channel_id: int = data.get('channel_id')
        self.message_id: int = data.get('message_id')
        self.message_is_deleted: bool = data.get('message_is_deleted')

        self.reward: int = data.get('reward')

        self.start_date: mido_utils.Time = mido_utils.Time(start_date=data.get('start_date'))
        self.end_date: mido_utils.Time = mido_utils.Time(end_date=data.get('end_date'))
        self.attenders: Set[int] = set(data.get('attenders'))

    @property
    def channel(self) -> discord.TextChannel:
        return self.bot.get_channel(self.channel_id)

    async def fetch_message_object(self) -> Optional[discord.Message]:
        if self.channel:
            try:
                return await self.channel.fetch_message(self.message_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None

    @classmethod
    async def get(cls,
                  bot,
                  event_id: int = None,
                  guild_id: int = None,
                  channel_id: int = None,
                  message_id: int = None) -> List[DonutEvent]:
        ret = await bot.db.fetch("""SELECT * FROM donut_events 
        WHERE id=$1 OR guild_id=$2 OR channel_id=$3 OR message_id=$4;""", event_id, guild_id, channel_id, message_id)

        return [cls(x, bot) for x in ret]

    @classmethod
    async def get_active_ones(cls, bot) -> List[DonutEvent]:
        ret = await bot.db.fetch("SELECT * FROM donut_events "
                                 "WHERE guild_id=ANY($1) AND message_is_deleted IS FALSE;",
                                 [x.id for x in bot.guilds])

        return [cls(x, bot) for x in ret]

    @classmethod
    async def create(cls,
                     bot,
                     reward: int,
                     guild_id: int,
                     channel_id: int,
                     message_id: int,
                     length: mido_utils.Time):
        ret = await bot.db.fetchrow(
            """INSERT INTO donut_events(reward, guild_id, channel_id, message_id, start_date, end_date) 
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING  *;""",
            reward, guild_id, channel_id, message_id, datetime.now(timezone.utc), length.end_date)

        return cls(ret, bot)

    async def add_attender(self, attender_id: int):
        self.attenders.add(attender_id)
        await self.db.execute("UPDATE donut_events SET attenders=ARRAY_APPEND(attenders, $1) WHERE id=$2;",
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

        e = mido_utils.Embed(bot=self.bot,
                             description=f"You have been awarded **{mido_utils.readable_currency(self.reward)}** "
                                         f"for attending the donut event!")
        try:
            await user_db.discord_obj.send(embed=e)
        except discord.Forbidden:
            pass

    async def delete_msg_and_mark_as_deleted(self, delay: float = None):
        """delay in seconds"""
        if delay:
            await asyncio.sleep(delay)

        msg = await self.fetch_message_object()
        if msg:
            await msg.delete()

        self.message_is_deleted = True

        await self.bot.db.execute("UPDATE donut_events SET message_is_deleted = TRUE WHERE id=$1;", self.id)

    def __eq__(self, other):
        if isinstance(other, DonutEvent):
            return self.id == other.id


class TransactionLog(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS transaction_history
(
    id      serial,
    user_id bigint                                 NOT NULL,
    amount  bigint                                 NOT NULL,
    reason  text                                   NOT NULL,
    date    timestamp WITH TIME ZONE DEFAULT NOW() NOT NULL
);

"""

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
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS blacklist
(
    user_or_guild_id bigint                                        NOT NULL,
    type             text                     DEFAULT 'user'::text NOT NULL,
    reason           text,
    date             timestamp WITH TIME ZONE DEFAULT NOW()        NOT NULL,
    CONSTRAINT blacklist_pk
        PRIMARY KEY (user_or_guild_id, type)
);"""

    class BlacklistType(Enum):
        guild = auto()
        user = auto()

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.type: str = data.get('type')
        self.reason: str = data.get('reason')
        self.date = mido_utils.Time(data.get('date'))

    @classmethod
    async def get(cls, bot, user_or_guild_id: int, bl_type: BlacklistType):
        ret = await bot.db.fetchrow("SELECT * FROM blacklist WHERE user_or_guild_id=$1 AND type=$2;",
                                    user_or_guild_id, bl_type.name)
        if not ret:
            return None
        else:
            return cls(ret, bot)

    @classmethod
    async def blacklist(cls,
                        bot,
                        user_or_guild_id: int,
                        bl_type: BlacklistType,
                        reason: str = None):
        ret = await bot.db.fetchrow(
            "INSERT INTO blacklist(user_or_guild_id, type, reason) VALUES ($1, $2, $3) RETURNING *;",
            user_or_guild_id, bl_type.name, reason
        )

        return cls(ret, bot)

    @classmethod
    async def unblacklist(cls,
                          bot,
                          user_or_guild_id: int,
                          bl_type: BlacklistType):

        return await bot.db.execute(
            "DELETE FROM blacklist WHERE user_or_guild_id=$1 AND type=$2;",
            user_or_guild_id, bl_type.name
        )


class XpRoleReward(BaseDBModel):
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS guilds_xp_role_rewards
(
    guild_id   bigint,
    level      integer,
    role_id    bigint,
    date_added timestamp WITH TIME ZONE
);
"""

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
    TABLE_DEFINITION = """CREATE TABLE IF NOT EXISTS hangman_words
(
    id       serial,
    category text,
    word     text
);
"""

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.word = data.get('word')
        self.category = data.get('category')

    def __repr__(self):
        return self.word

    @classmethod
    async def get_categories_and_counts(cls, bot) -> Dict[str, int]:
        ret = await bot.db.fetch("SELECT category, COUNT(category) AS count FROM hangman_words GROUP BY category;")
        return {category: count for category, count in ret}

    @classmethod
    async def add_word(cls, bot, category: str, word: str) -> HangmanWord:
        ret = await bot.db.fetchrow("INSERT INTO hangman_words(category, word) VALUES ($1, $2) RETURNING *;",
                                    category, word)
        return cls(ret, bot)

    @classmethod
    async def add_words(cls, bot, category: str, words: List[str]) -> None:
        await bot.db.executemany(
            "INSERT INTO hangman_words(category, word) VALUES ($1, $2) ON CONFLICT DO NOTHING;",
            ((category, word) for word in words)
        )

    @classmethod
    async def get_random_word(cls, bot, category: str) -> HangmanWord:
        ret = await bot.db.fetchrow("SELECT * FROM hangman_words WHERE category = $1 ORDER BY RANDOM() LIMIT 1;",
                                    category)
        return cls(ret, bot)


class RepeatDB(BaseDBModel):
    TABLE_DEFINITION = """
CREATE TABLE IF NOT EXISTS guilds_repeat
(
    id                   serial
        CONSTRAINT guilds_repeat_pk
            PRIMARY KEY,
    guild_id             bigint                                 NOT NULL,
    channel_id           bigint                                 NOT NULL,
    creation_date        timestamp WITH TIME ZONE DEFAULT NOW() NOT NULL,
    post_interval        bigint                                 NOT NULL,
    message              text                                   NOT NULL,
    delete_previous      boolean                  DEFAULT TRUE  NOT NULL,
    last_post_date       timestamp WITH TIME ZONE,
    created_by           bigint                                 NOT NULL,
    last_post_message_id bigint
);
"""

    def __init__(self, data: Record, bot):
        super().__init__(data, bot)

        self.guild_id: int = data.get('guild_id')
        self.channel_id: int = data.get('channel_id')

        self.message: str = data.get('message')
        self.post_interval: int = data.get('post_interval')
        self.delete_previous: bool = data.get('delete_previous')

        self.creation_date: mido_utils.Time = mido_utils.Time(start_date=data.get('creation_date'))

        self.last_post_date: mido_utils.Time = mido_utils.Time(
            data.get('last_post_date', datetime(2000, 1, 1, tzinfo=timezone.utc)))
        self.last_post_message_id: int = data.get('last_post_message_id')

        self.created_by_id: int = data.get('created_by')

    @property
    def guild(self) -> Optional[discord.Guild]:
        return self.bot.get_guild(self.guild_id)

    @property
    def channel(self) -> Optional[discord.TextChannel]:
        return self.bot.get_channel(self.channel_id)

    @classmethod
    async def create(cls,
                     bot,
                     guild_id: int,
                     channel_id: int,
                     message: str,
                     post_interval: int,
                     created_by_id: int,
                     delete_previous: bool = True) -> RepeatDB:
        created = await bot.db.fetchrow(
            """INSERT INTO 
            guilds_repeat(guild_id, channel_id, message, post_interval, delete_previous, created_by) 
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING *;""",
            guild_id, channel_id, message, post_interval, delete_previous, created_by_id)

        return cls(created, bot)

    @classmethod
    async def get_all(cls, bot) -> List[RepeatDB]:
        guild_ids = [x.id for x in bot.guilds]
        ret = await bot.db.fetch("SELECT * FROM guilds_repeat WHERE guild_id=ANY($1);", guild_ids)

        return [cls(repeat, bot) for repeat in ret]

    @classmethod
    async def get_of_a_guild(cls, bot, guild_id: int) -> List[RepeatDB]:
        ret = await bot.db.fetch("SELECT * FROM guilds_repeat WHERE guild_id=$1;", guild_id)

        return sorted((cls(repeat, bot) for repeat in ret), key=lambda x: x.creation_date.start_date)

    async def just_posted(self, message_id: int):
        self.last_post_date = mido_utils.Time()
        self.last_post_message_id = message_id
        await self.bot.db.execute("UPDATE guilds_repeat SET last_post_date=$1, last_post_message_id=$2 WHERE id=$3;",
                                  self.last_post_date.start_date, message_id, self.id)

    async def delete(self):
        await self.bot.db.execute("DELETE FROM guilds_repeat WHERE id=$1;", self.id)

    def __eq__(self, other):
        if isinstance(other, RepeatDB):
            return self.id == other.id
