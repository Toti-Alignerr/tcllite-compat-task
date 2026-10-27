"""Exceptions used for errors and for non-local control flow."""


class TclError(Exception):
    """A Tcl error; the message is the error result."""

    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


class ReturnException(Exception):
    def __init__(self, value, code=2, level=1):
        super().__init__(value)
        self.value = value
        self.code = code
        self.level = level


class BreakException(Exception):
    pass


class ContinueException(Exception):
    pass


class ExitException(Exception):
    def __init__(self, status):
        super().__init__(status)
        self.status = status
