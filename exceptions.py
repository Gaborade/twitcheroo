class TwitchException(Exception):
    pass


class ScopeError(Exception):
    pass


class InvalidRequestException(Exception):
    pass


class TwitchAuthException(Exception):
    pass


class TwitchClientCredentialsException(TwitchAuthException):
    
    def __init__(self, message, reason):
        super(TwitchClientCredentialsError, self).__init__()
        self.message = message
        self.reason = reason


