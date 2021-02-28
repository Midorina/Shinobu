from discord import Color as discordColor


class Color(discordColor):
    def __init__(self, value):
        super().__init__(value)

    @classmethod
    def mido_green(cls):
        return cls(0x15a34a)

    @classmethod
    def shino_yellow(cls):
        return cls(0xfffe91)

    @classmethod
    def success(cls):
        return cls(0x00ff00)

    @classmethod
    def fail(cls):
        return cls(0xff0000)

    @classmethod
    def eight_ball_green(cls):
        return cls(0x008000)

    @classmethod
    def eight_ball_yellow(cls):
        return cls(0xffd700)

    @classmethod
    def eight_ball_red(cls):
        return cls.fail()
