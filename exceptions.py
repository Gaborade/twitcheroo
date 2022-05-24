class TwitchException(Exception):
    pass


class ScopeError(TwitchException):
    pass


class InvalidRequestException(TwitchException):
    pass


class TwitchAuthException(TwitchException):
    pass


class BadRequestError(TwitchException):
    pass


class TwitchClientCredentialsException(TwitchAuthException):
    def __init__(self, message, reason):
        super(TwitchClientCredentialsError, self).__init__()
        self.message = message
        self.reason = reason
