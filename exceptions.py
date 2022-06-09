from requests.exceptions import ConnectionError


class TwitchException(Exception):
    pass


class ScopeError(TwitchException):
    pass


class InvalidRequestException(TwitchException):
    pass


class TwitchAuthException(TwitchException):
    pass


class TwitchInternalServerError(TwitchException):
    pass


class NetworkConnectionError(ConnectionError):
    pass


class HTTPStatusError(TwitchException):
    def __init__(self, error_msg):
        self.error_msg = error_msg
        print(self)

    def __str__(self):
        msg = self.error_msg.get("message", None)
        status_code = self.error_msg["status"]
        return f" message: {msg}, status_code={status_code}"


class UnAuthorizedError(HTTPStatusError):
    def __init__(self, message):
        super(UnAuthorizedError, self).__init__(message)


class BadRequestError(HTTPStatusError):
    def __init__(self, message):
        super(BadRequestError, self).__init__(message)


class TooManyRequestsError(HTTPStatusError):
    def __init__(self, message):
        super(TooManyRequestsError, self).__init__(message)


class ForbiddenError(HTTPStatusError):
    def __init__(self, message):
        super(ForbiddenError).__init__(message)
