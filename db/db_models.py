from datetime import datetime, timezone
from typing import Tuple

from asyncpg import Record, pool

from services import time_stuff


class OnCooldown(Exception):
    pass


class UserDB:
    def __init__(self, user_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data = user_db

        self.id: int = user_db.get('id')
        self.cash: int = user_db.get('cash')
        self.xp: int = user_db.get('xp')

        self.last_daily_claim_date = user_db.get('last_daily_claim')
        self.last_xp_gain_date = user_db.get('last_xp_gain')

    @property
    def can_gain_xp_remaining(self) -> Tuple[bool, int]:
        remaining = time_stuff.get_time_difference(self, "xp")
        return remaining <= 0, remaining

    @property
    def can_claim_daily_remaining(self) -> Tuple[bool, int]:
        remaining = time_stuff.get_time_difference(self, "daily")
        return remaining <= 0, remaining

    async def add_xp(self, amount: int) -> int:
        can_gain, remaining = self.can_gain_xp_remaining

        if can_gain:
            await self._db.execute(
                """UPDATE users SET xp = xp + $1, last_xp_gain = $2 where id=$3""",
                amount, datetime.now(timezone.utc), self.id)

            self.xp += amount
            return self.xp
        else:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{time_stuff.parse_seconds(remaining)}**.")

    async def remove_xp(self, amount: int) -> int:
        await self._db.execute(
            """UPDATE users SET xp = xp - $1 where id=$2""",
            amount, self.id)

        self.xp -= amount
        return self.xp

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
