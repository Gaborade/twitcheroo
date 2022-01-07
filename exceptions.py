class TwitchException(Exception):
    pass


class TwitchClientCredentialsException(TwitchException):
    
    def __init__(self, message, reason):
        super(TwitchClientCredentialsError, self).__init__()
        self.message = message
        self.reason = reason


