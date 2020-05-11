from datetime import datetime, timezone
from typing import Tuple, List

from asyncpg import Record, pool

from db import db_funcs
from services import time_stuff


class OnCooldown(Exception):
    pass


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

        self.total_xp: int = user_db.get('xp')
        self.level, self.progress, self.required_xp_to_level_up = calculate_xp_data(self.total_xp)
        self.last_xp_gain_date = user_db.get('last_xp_gain')

        self.last_daily_claim_date = user_db.get('last_daily_claim')

    @property
    def can_gain_xp_remaining(self) -> Tuple[bool, int]:
        remaining = time_stuff.get_time_difference(self, "xp")
        return remaining <= 0, remaining

    @property
    def can_claim_daily_remaining(self) -> Tuple[bool, int]:
        remaining = time_stuff.get_time_difference(self, "daily")
        return remaining <= 0, remaining

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
        can_gain, remaining = self.can_gain_xp_remaining

        if not can_gain and not owner:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{time_stuff.parse_seconds(remaining)}**.")
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
        self.last_xp_gain_date = member_db.get('last_xp_gain')

    async def assign_user_and_guild_objs(self):
        self.guild = await db_funcs.get_guild_db(self._db, self.data.get('guild_id'))
        self.user = await db_funcs.get_user_db(self._db, self.id)

    @property
    def can_gain_xp_remaining(self) -> Tuple[bool, int]:
        remaining = time_stuff.get_time_difference(self, "xp")
        return remaining <= 0, remaining

    async def add_xp(self, amount: int, owner=False) -> int:
        can_gain, remaining = self.can_gain_xp_remaining

        if not can_gain and not owner:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{time_stuff.parse_seconds(remaining)}**.")
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

    async def change_prefix(self, new_prefix: str) -> str:
        await self._db.execute(
            """UPDATE guilds SET prefix=$1 where id=$2;""", new_prefix, self.id)

        self.prefix = new_prefix
        return self.prefix

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
        top_10 = await self._db.fetch("""SELECT * FROM members ORDER BY xp DESC LIMIT 10;""")
        return [MemberDB(user, self._db) for user in top_10]
