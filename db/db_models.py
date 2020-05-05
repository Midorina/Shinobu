from datetime import datetime, timezone

from services import time_stuff
from asyncpg import Record, pool


class OnCooldown(Exception):
    pass


class UserDB:
    def __init__(self, user_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data = user_db

        self.id = user_db.get('id')
        self.cash = user_db.get('cash')
        self.xp = user_db.get('xp')

        self.last_daily_claim_date = user_db.get('last_daily_claim')
        self.last_xp_gain_date = user_db.get('last_xp_gain')

        self.daily_remaining_time = time_stuff.get_cooldown_remaining(self, "daily")
        self.xp_remaining_time = time_stuff.get_cooldown_remaining(self, "xp")

    @property
    def can_gain_xp_remaining(self):
        remaining = time_stuff.get_cooldown_remaining(self, "xp")
        return remaining <= 0, remaining

    async def gain_xp(self, amount=0):
        can_gain, remaining = self.can_gain_xp_remaining

        if can_gain:
            await self._db.execute(
                """UPDATE users SET xp = xp + $1, last_xp_gain = $2 where id=$3""",
                amount, datetime.now(timezone.utc), self.id)
        else:
            raise OnCooldown(f"You're still on cooldown! "
                             f"Try again after **{time_stuff.parse_seconds(remaining)}**.")

    @property
    def can_claim_daily_remaining(self):
        remaining = time_stuff.get_cooldown_remaining(self, "daily")
        return remaining <= 0, remaining

    async def add_cash(self, amount: int = 0, daily=False):
        if daily:
            await self._db.execute("""UPDATE users SET cash = cash + $1, last_daily_claim=$2 where id=$3;""",
                                   amount, datetime.now(timezone.utc), self.id)
        else:
            await self._db.execute("""UPDATE users SET cash = cash + $1 where id=$2;""",
                                   amount, self.id)

        self.cash += amount

    async def remove_cash(self, amount: int):
        await self._db.execute("""UPDATE users SET cash = cash - $1 where id=$2;""", amount, self.id)
        self.cash -= amount


class GuildDB:
    def __init__(self, guild_db: Record, db_conn: pool.Pool):
        self._db = db_conn

        self.data = guild_db

        self.id = guild_db.get('id')
        self.prefix = guild_db.get('prefix')
        self.delete_commands = guild_db.get('delete_commands')

    async def change_prefix(self, new_prefix: str):
        await self._db.execute("""UPDATE guilds SET prefix=$1 where id=$2;""", new_prefix, self.id)
