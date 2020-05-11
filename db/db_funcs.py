import json

import asyncpg

from db.db_models import UserDB, GuildDB, MemberDB

with open('config.json') as f:
    config = json.load(f)


async def get_prefix_dict(db: asyncpg.pool.Pool) -> dict:
    return dict(await db.fetch("""SELECT id, prefix FROM guilds;"""))


async def insert_new_user(db: asyncpg.pool.Pool, user_id: int):
    await db.execute(
        """INSERT INTO users (id) values($1) ON CONFLICT DO NOTHING;""", user_id)


async def insert_new_member(db: asyncpg.pool.Pool, guild_id: int, member_id: int):
    await insert_new_user(db, member_id)
    await db.execute(
        """INSERT INTO members (guild_id, user_id) values($1, $2) ON CONFLICT DO NOTHING;""", guild_id, member_id)


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


async def get_member_db(db: asyncpg.pool.Pool, guild_id: int, member_id: int) -> MemberDB:
    member_db = None

    while not member_db:
        # not using inner join cuz it complicates things
        member_db = await db.fetchrow(
            """
            SELECT
                *
            FROM 
                members 
            WHERE 
                guild_id=$1 and user_id=$2;""", guild_id, member_id)

        if not member_db:  # if not exists insert user
            await insert_new_member(db, guild_id, member_id)

    m = MemberDB(member_db, db)
    await m.assign_user_and_guild_objs()
    return m


async def get_guild_db(db: asyncpg.pool.Pool, guild_id: int) -> GuildDB:
    guild_db = None

    while not guild_db:
        guild_db = await db.fetchrow(
            """SELECT * from guilds where id=$1;""", guild_id)

        if not guild_db:  # if not exists insert guild
            await insert_new_guild(db, guild_id)

    return GuildDB(guild_db, db)




