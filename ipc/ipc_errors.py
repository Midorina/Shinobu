class BaseIPCError(Exception):
    pass


class UnknownRequestType(BaseIPCError):
    pass
