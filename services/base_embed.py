from datetime import datetime

import discord


class BaseEmbed(discord.Embed):
    def __init__(self, bot, footer=True, image_url=None, **kwargs):
        super().__init__(**kwargs)
        self.bot = bot

        self.color = self.color if self.color else 0x15a34a

        if footer is True and not hasattr(self, '_footer'):
            self.set_footer(text=self.bot.user.name, icon_url=self.bot.user.avatar_url)

            self.timestamp = self.timestamp if self.timestamp else datetime.utcnow()

        if image_url:
            self.set_image(url=image_url)
