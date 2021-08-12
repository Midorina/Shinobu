from discord.ext.commands import CommandError


class BaseIPCError(Exception):
    pass


class UnknownRequestType(BaseIPCError):
    pass


class RequestFailed(CommandError):
    pass
