from datetime import datetime

import discord


class BaseEmbed(discord.Embed):
    def __init__(self, bot, default_footer=False, image_url=None, **kwargs):
        super().__init__(**kwargs)
        self.bot = bot

        self.color = self.color if self.color else 0x15a34a

        # if default_footer is True and not hasattr(self, '_footer'):
        if default_footer is True:
            self.set_footer(text=self.bot.user.name, icon_url=self.bot.user.avatar_url)

            self.timestamp = self.timestamp or datetime.utcnow()

        if image_url:
            self.set_image(url=image_url)
