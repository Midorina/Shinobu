from discord.ext import commands

from db.models import UserDB, GuildDB, MemberDB


class Context(commands.Context):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = self.bot.db

        self.guild_db: GuildDB = None
        self.member_db: MemberDB = None
        self.user_db: UserDB = None

    async def attach_db_objects(self):
        try:
            self.member_db = await MemberDB.get_or_create(self.db, self.guild.id, self.author.id)
            self.guild_db = self.member_db.guild
            self.user_db = self.member_db.user

            self.prefix = self.guild_db.prefix
        except AttributeError:
            self.user_db = await UserDB.get_or_create(self.db, self.author.id)
