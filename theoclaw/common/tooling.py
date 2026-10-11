"""What every tool handler shares, whichever module defines the tool."""

from typing import Callable

Handler = Callable[[dict], str]  # tool input -> text returned to the model


class ToolError(Exception):
    """A failure the model should be told about (sent back with is_error=True)."""
