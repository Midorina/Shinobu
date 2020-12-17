from discord.ext.commands import CommandError


class OnCooldownError(CommandError):
    pass


class DidntVoteError(CommandError):
    pass


class SilentError(CommandError):
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


class APIError(CommandError):
    pass


class TimedOut(CommandError):
    pass


class UserIsBlacklisted(CommandError):
    pass


class GuildIsBlacklisted(CommandError):
    pass


# race exceptions

class RaceError(CommandError):
    pass
