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


class UnknownCurrency(CommandError):
    pass


class TimedOut(CommandError):
    pass


class UserIsBlacklisted(CommandError):
    pass


class GuildIsBlacklisted(CommandError):
    pass


class IncompleteConfigFile(CommandError):
    pass


# race exceptions

class RaceError(CommandError):
    pass


# patron
class NotPatron(CommandError):
    pass


class InsufficientPatronLevel(CommandError):
    pass


class CantClaimRightNow(CommandError):
    pass


# backend exceptions

class UnknownNSFWType(Exception):
    def __init__(self, nsfw_type):
        self.nsfw_type = nsfw_type
        super().__init__(f'Unsupported NSFW type: {nsfw_type.name}')


class MessageTooLong(Exception):
    def __init__(self, message_content: str):
        self.message_content = message_content
        super().__init__(f'Message is too long to post on Discord: {message_content}')
