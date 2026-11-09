class UserError(Exception):
    """A safe, user-facing message. Must never contain tokens or passwords."""


class Cancelled(Exception):
    """The user pressed Stop or said no. May carry a short friendly message."""
