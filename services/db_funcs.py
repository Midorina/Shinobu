import asyncpg
import json

from services.db_models import UserDB, GuildDB
from datetime import datetime, timezone

with open('config.json') as f:
    config = json.load(f)


async def get_server_prefix(db: asyncpg.pool.Pool, guild_id: int = None):
    if guild_id is None:
        prefix = config["default_prefix"]

    else:
        guild_db = await get_guild_db(db, guild_id)
        prefix = guild_db.prefix

    return prefix


async def insert_new_user(db: asyncpg.pool.Pool, user_id: int):
    await db.execute(
        """INSERT INTO users (id) values($1) ON CONFLICT DO NOTHING;""", user_id)


async def insert_new_guild(db: asyncpg.pool.Pool, guild_id: int):
    await db.execute(
        """INSERT INTO guilds(id) VALUES ($1) ON CONFLICT DO NOTHING""", guild_id)


async def get_user_db(db: asyncpg.pool.Pool, user_id: int) -> UserDB:
    user_db = None

    while not user_db:
        user_db = await db.fetchrow(
            """SELECT * from users where id=$1;""", user_id)

        if not user_db:  # if not exists create user info
            await insert_new_user(db, user_id)

    return UserDB(user_db)


async def get_guild_db(db: asyncpg.pool.Pool, guild_id: int) -> GuildDB:
    guild_db = None

    while not guild_db:
        guild_db = await db.fetchrow(
            """SELECT * from guilds where id=$1;""", guild_id)

        if not guild_db:  # if not exists insert guild
            await insert_new_guild(db, guild_id)

    return GuildDB(guild_db)


async def add_cash(db: asyncpg.pool.Pool, user_id: int, amount: int, daily=False):
    if daily:
        await db.execute("""UPDATE users SET cash = cash + $1, last_daily_claim=$2 where id=$3;""",
                         amount, datetime.now(timezone.utc), user_id)

    else:
        await db.execute("""UPDATE users SET cash = cash + $1 where id=$2;""",
                         amount, user_id)


async def remove_cash(db: asyncpg.pool.Pool, user_id: int, amount: int):
    # user = await get_user_db(db, user_id)
    # if user.cash < 0:
    #     raise Exception("Their money is already 0. We can't withdraw any further.")

    await db.execute("""UPDATE users SET cash = cash - $1 where id=$2;""", amount, user_id)



