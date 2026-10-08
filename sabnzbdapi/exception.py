from json import JSONDecodeError

from niquests.exceptions import RequestException


class APIError(Exception):
    """Base error for all exceptions from this Client."""


class APIConnectionError(RequestException, APIError):
    """Base class for all communications errors including HTTP errors."""


class APIResponseError(APIError, JSONDecodeError):
    """Base class for all errors from the API response."""

    def __init__(self, msg, doc="", pos=0):
        JSONDecodeError.__init__(self, msg, doc, pos)


class LoginFailed(APIConnectionError, JSONDecodeError):
    """This can technically be raised with any request since log in may be attempted for
    any request and could fail."""


class NotLoggedIn(APIConnectionError):
    """Raised when login is not successful."""
