"""Errors that tools raise for front ends to show to the user."""


class ToolError(Exception):
    """A failure caused by the user's input; its message is fit to show them as is."""
