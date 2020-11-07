from discord.ext.commands import CommandError


class EmbedError(CommandError):
    pass


class SilenceError(CommandError):
    pass


class NotFoundError(CommandError):
    pass


class MusicError(CommandError):
    pass


class InvalidURL(CommandError):
    pass


class InsufficientCash(CommandError):
    pass


class RateLimited(CommandError):
    pass


class TooManyArgs(CommandError):
    pass
