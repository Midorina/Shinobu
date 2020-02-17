from services import time_stuff


class UserDB:
    def __init__(self, user_db):
        self.data = user_db

        self.id = user_db['id']
        self.cash = user_db['cash']
        self.xp = user_db['xp']

        self.last_daily_claim_date = user_db['last_daily_claim']
        self.last_xp_gain_date = user_db['last_xp_gain']

        self.daily_remaining_time = time_stuff.get_cooldown(self, "daily")
        self.xp_remaining_time = time_stuff.get_cooldown(self, "xp")


class GuildDB:
    def __init__(self, guild_db):
        self.data = guild_db

        self.id = guild_db['id']
        self.prefix = guild_db['prefix']
        self.delete_commands = guild_db['delete_commands']
