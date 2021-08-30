from shinobu import ShinobuBot


class BaseShinobuService:
    def __init__(self, bot: ShinobuBot):
        self.bot = bot
