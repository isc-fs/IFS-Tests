from __future__ import annotations


class UserError(Exception):
    """A user-facing error. `fields` maps form fields to messages when the form can show them inline."""

    def __init__(self, message: str, status: int = 400, fields: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.fields = fields or {}
