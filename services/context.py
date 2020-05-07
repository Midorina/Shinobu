from discord.ext import commands

from db import db_funcs
from db.db_models import UserDB, GuildDB


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = self.bot.db

        self.author_db: UserDB = None
        self.guild_db: GuildDB = None

    async def attach_db_objects(self):
        self.author_db = await db_funcs.get_user_db(self.db, self.author.id)

        try:
            self.guild_db = await db_funcs.get_guild_db(self.db, self.guild.id)
            self.prefix = self.guild_db.prefix
        except AttributeError:
            pass
