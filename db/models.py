import json
from datetime import datetime, timezone
from enum import Enum
from typing import List

from asyncpg import Record, pool

from services.time import MidoTime

with open('config.json') as f:
    config = json.load(f)


class OnCooldown(Exception):
    pass


class XpAnnouncement(Enum):
    SILENT = 0
    DM = 1
    GUILD = 2


class ModLog:
    class Type(Enum):
        MUTE = 0
        UNMUTE = 1
        KICK = 1
        BAN = 2
        UNBAN = 3

    def __init__(self, modlog_db: Record, db_conn: pool.Pool):
        self._db = db_conn
        self.data = modlog_db

        self.id = modlog_db.get('id')

        self.guild_id = modlog_db.get('guild_id')
        self.user_id = modlog_db.get('user_id')

        self.type = ModLog.Type(modlog_db.get('type'))
        self.reason = modlog_db.get('reason')
        self.executor_id = modlog_db.get('executor_id')

        self.date = modlog_db.get('date')
        self.length_string = MidoTime.parse_seconds_to_str(modlog_db.get('length_in_seconds'))
        self.time_status = MidoTime.add_to_previous_date_and_get(self.date, modlog_db.get('length_in_seconds'))

        self.done = modlog_db.get('done')

    @classmethod
    async def get_by_id(cls, db: pool.Pool, guild_id: int, log_id: int):
        log = await db.fetchrow("""SELECT * FROM modlogs WHERE id=$1 and guild_id=$2;""", log_id, guild_id)

        return cls(log, db) if log else None

    @classmethod
    async def get_logs(cls, db: pool.Pool, guild_id: int, user_id: int):
        logs = await db.fetch(
            """SELECT * FROM modlogs WHERE guild_id=$1 and user_id=$2 and hidden=FALSE ORDER BY date DESC;""",
            guild_id, user_id)

        return [cls(log, db) for log in logs]

    @classmethod
    async def add_modlog(cls,
                         db_conn: pool.Pool,
                         guild_id: int,
                         user_id: int,
                         type: Type,
                         executor_id: int,
                         reason: str = None,
                         length: MidoTime = None,
                         ):
        new_modlog_db = await db_conn.fetchrow(
            """INSERT INTO 
            modlogs (guild_id, user_id, type, reason, executor_id, length_in_seconds, date) 
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *;""",
            guild_id,
            user_id,
            type.value,
            reason,
            executor_id,
            getattr(length, 'remaining_in_seconds', None),
            datetime.now(timezone.utc)
        )

        return cls(new_modlog_db, db_conn)

    async def delete_from_db(self):
        await self._db.execute("""DELETE from modlogs WHERE id=$1;""", self.id)

    async def complete(self):
        await self._db.execute("""UPDATE modlogs SET done=True WHERE id=$1;""", self.id)

    async def change_reason(self, new_reason: str):
        await self._db.execute("""UPDATE modlogs SET reason=$1 WHERE id=$2;""", new_reason, self.id)

    @staticmethod
    async def hide_logs(db: pool.Pool, guild_id: int, user_id: int):
        await db.execute(
            """UPDATE modlogs SET hidden=TRUE WHERE guild_id=$1 and user_id=$2;""", guild_id, user_id)


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


class UserDB:
    def __init__(self, user_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data = user_db

        self.id: int = user_db.get('id')
        self.cash: int = user_db.get('cash')

        self.level_up_notification = XpAnnouncement(user_db.get('level_up_notification'))
        self.total_xp: int = user_db.get('xp')
        self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
        self.xp_status = MidoTime.add_to_previous_date_and_get(
            user_db.get('last_xp_gain'), config['cooldowns']['xp'])

        self.daily_date_status = MidoTime.add_to_previous_date_and_get(user_db.get('last_daily_claim'),
                                                                       config['cooldowns']['daily'])

    @classmethod
    async def get_or_create(cls, db: pool.Pool, user_id: int):
        user_db = await db.fetchrow("""SELECT * FROM users WHERE id=$1;""", user_id)
        if not user_db:
            user_db = await db.fetchrow(
                """INSERT INTO users (id) values($1) RETURNING *;""", user_id)

        return cls(user_db, db)

    async def change_level_up_preference(self, new_preference: XpAnnouncement):
        await self._db.execute("""UPDATE users SET level_up_notification=$1 WHERE id=$2;""", new_preference.value, self.id)

    async def add_cash(self, amount: int, daily=False) -> int:
        if daily:
            await self._db.execute(
                """UPDATE users SET cash = cash + $1, last_daily_claim=$2 where id=$3;""",
                amount, datetime.now(timezone.utc), self.id)
        else:
            await self._db.execute(
                """UPDATE users SET cash = cash + $1 where id=$2;""",
                amount, self.id)

        self.cash += amount
        return self.cash

    async def remove_cash(self, amount: int) -> int:
        await self._db.execute(
            """UPDATE users SET cash = cash - $1 where id=$2;""", amount, self.id)

        self.cash -= amount
        return self.cash

    async def add_xp(self, amount: int, owner=False) -> int:
        if not self.xp_status.end_date_has_passed and not owner:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{self.xp_status.remaining_string}**.")
        else:
            await self._db.execute(
                """UPDATE users SET xp = xp + $1, last_xp_gain = $2 where id=$3""",
                amount, datetime.now(timezone.utc), self.id)

            self.total_xp += amount
            # im just too lazy
            self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
            return self.total_xp

    async def remove_xp(self, amount: int) -> int:
        await self._db.execute(
            """UPDATE users SET xp = xp - $1 where id=$2""",
            amount, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self._db.fetchrow("""
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

    async def get_top_10(self):
        top_10 = await self._db.fetch("""SELECT * FROM users ORDER BY xp DESC LIMIT 10;""")
        return [UserDB(user, self._db) for user in top_10]


class MemberDB:
    def __init__(self, member_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data = member_db

        self.id: int = member_db.get('user_id')
        self.guild: GuildDB = None
        self.user: UserDB = None

        self.total_xp: int = member_db.get('xp')

        self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
        self.xp_date_status = MidoTime.add_to_previous_date_and_get(
            member_db.get('last_xp_gain'), config['cooldowns']['xp'])

    @classmethod
    async def get_or_create(cls, db: pool.Pool, guild_id: int, member_id: int):
        user_db = await UserDB.get_or_create(db, member_id)
        guild_db = await GuildDB.get_or_create(db, guild_id)

        member_db = await db.fetchrow(
            """SELECT * FROM members WHERE guild_id=$1 and user_id=$2;""", guild_id, member_id)

        if not member_db:
            member_db = await db.fetchrow(
                """INSERT INTO members (guild_id, user_id) values($1, $2) RETURNING *;""", guild_id, member_id)

        member_obj = cls(member_db, db)
        member_obj.guild = guild_db
        member_obj.user = user_db

        return member_obj

    async def add_xp(self, amount: int, owner=False) -> int:
        if not self.xp_date_status.end_date_has_passed and not owner:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{self.xp_date_status.remaining_string}**.")
        else:
            await self._db.execute(
                """UPDATE members SET xp = xp + $1, last_xp_gain = $2 where guild_id=$3 and user_id=$4""",
                amount, datetime.now(timezone.utc), self.guild.id, self.id)

            self.total_xp += amount
            # im just too lazy
            self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
            return self.total_xp

    async def remove_xp(self, amount: int) -> int:
        await self._db.execute(
            """UPDATE members SET xp = xp - $1 WHERE guild_id=$2 AND user_id=$3;""",
            amount, self.guild.id, self.id)

        self.total_xp -= amount
        return self.total_xp

    async def get_xp_rank(self) -> int:
        result = await self._db.fetchrow("""
            WITH counts AS (
                SELECT DISTINCT
                    guild_id,
                    user_id,
                    ROW_NUMBER () OVER (ORDER BY xp DESC)
                FROM
                    members
            ) SELECT
                *
            FROM
                counts
            WHERE
                guild_id=$1 AND user_id=$2;
            """, self.guild.id, self.id)

        return result['row_number']


class GuildDB:
    def __init__(self, guild_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data: Record = guild_db

        self.id: int = guild_db.get('id')
        self.prefix: str = guild_db.get('prefix')

        self.delete_commands: bool = guild_db.get('delete_commands')
        self.level_up_notifs_silenced: bool = guild_db.get('level_up_notifs_silenced')

        self.volume: int = guild_db.get('volume')

    @classmethod
    async def get_or_create(cls, db: pool.Pool, guild_id: int):
        guild_db = await db.fetchrow("""SELECT * from guilds where id=$1;""", guild_id)

        if not guild_db:
            guild_db = await db.fetchrow(
                """INSERT INTO guilds(id) VALUES ($1) RETURNING *""", guild_id)

        return cls(guild_db, db)

    async def change_prefix(self, new_prefix: str) -> str:
        await self._db.execute(
            """UPDATE guilds SET prefix=$1 where id=$2;""", new_prefix, self.id)

        self.prefix = new_prefix
        return self.prefix

    async def change_volume(self, new_volume: int):
        await self._db.execute("""UPDATE guilds SET volume=$1 WHERE id=$2;""", new_volume, self.id)
        self.volume = new_volume

    async def toggle_delete_commands(self) -> bool:
        await self._db.execute(
            """
            UPDATE guilds 
            SET delete_commands = NOT delete_commands
            WHERE id=$1;
            """, self.id
        )

        self.delete_commands = not self.delete_commands
        return self.delete_commands

    async def toggle_level_up_notifs(self) -> bool:
        await self._db.execute(
            """
            UPDATE guilds 
            SET level_up_notifs_silenced = NOT level_up_notifs_silenced
            WHERE id=$1;
            """, self.id
        )

        self.level_up_notifs_silenced = not self.level_up_notifs_silenced
        return self.level_up_notifs_silenced

    async def get_top_10(self) -> List[MemberDB]:
        top_10 = await self._db.fetch("""SELECT * FROM members WHERE members.guild_id=$1 ORDER BY xp DESC LIMIT 10;""",
                                      self.id)
        return [MemberDB(user, self._db) for user in top_10]
