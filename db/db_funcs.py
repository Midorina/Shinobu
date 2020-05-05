import json

import asyncpg

from db.db_models import UserDB, GuildDB

with open('config.json') as f:
    config = json.load(f)


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

        if not user_db:  # if not exists insert user
            await insert_new_user(db, user_id)

    return UserDB(user_db, db)


async def get_guild_db(db: asyncpg.pool.Pool, guild_id: int) -> GuildDB:
    guild_db = None

    while not guild_db:
        guild_db = await db.fetchrow(
            """SELECT * from guilds where id=$1;""", guild_id)

        if not guild_db:  # if not exists insert guild
            await insert_new_guild(db, guild_id)

    return GuildDB(guild_db, db)




