"""Exception classes for the Odyssey client library."""

from __future__ import annotations

from typing import Any

# ASCII art logo for branded error messages
_ODYSSEY_LOGO = """\
    ___  ___  _   _ ____ ____ ____ _   _
   / _ \\|   \\ \\_/ / ___/ ___| ___\\ \\_/ /
  | (_) | |) |\\   /\\___ \\___ | ___ \\   /
   \\___/|___/  |_| |____/___/|____/ |_|"""

_BOX_WIDTH = 51  # Inner width of the error box


def _format_error_box(title: str, lines: list[str], action_url: str | None = None) -> str:
    """Format an error message in a branded ASCII box.

    Args:
        title: The error title (e.g., "Monthly usage limit reached")
        lines: Detail lines to display
        action_url: Optional URL for the user to take action

    Returns:
        Formatted multi-line string with ASCII box
    """
    border = "━" * (_BOX_WIDTH + 2)
    result = [f"┏{border}┓"]

    # Add logo lines
    for logo_line in _ODYSSEY_LOGO.split("\n"):
        result.append(f"┃ {logo_line.ljust(_BOX_WIDTH)} ┃")

    result.append(f"┣{border}┫")

    # Add title with error marker
    result.append(f"┃  ✗ {title.ljust(_BOX_WIDTH - 3)}┃")
    result.append(f"┃{' ' * (_BOX_WIDTH + 2)}┃")

    # Add content lines
    for line in lines:
        result.append(f"┃  {line.ljust(_BOX_WIDTH)}┃")

    # Add action URL
    if action_url:
        result.append(f"┃{' ' * (_BOX_WIDTH + 2)}┃")
        result.append(f"┃  → {action_url.ljust(_BOX_WIDTH - 2)}┃")

    result.append(f"┗{border}┛")

    return "\n".join(result)


class OdysseyError(Exception):
    """Base exception for all Odyssey client errors."""

    pass


class OdysseyAuthError(OdysseyError):
    """Authentication failed.

    Raised when:
    - API key is invalid or expired
    - API key lacks required permissions
    """

    pass


class OdysseyConnectionError(OdysseyError):
    """Connection to Odyssey failed.

    Raised when:
    - No streamers are available
    - Queue timeout expired
    - WebRTC connection failed
    - Signaling connection failed
    """

    pass


class OdysseyStreamError(OdysseyError):
    """Stream operation failed.

    Raised when:
    - Stream fails to start
    - Interaction fails
    - Stream ends unexpectedly
    """

    pass


# =============================================================================
# Usage/Account Limit Errors (with branded ASCII output)
# =============================================================================


class OdysseyUsageError(OdysseyError):
    """Base class for usage and account limit errors.

    These errors display with branded ASCII art to help developers
    quickly identify account-related issues and take action.
    """

    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        action_url: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize usage error.

        Args:
            code: Error code (e.g., "MONTHLY_LIMIT_REACHED")
            message: Human-readable error message
            action: Suggested action for the user
            action_url: URL where user can take action
            details: Additional error details (used_hours, limit, etc.)
        """
        super().__init__(message)
        self.code = code
        self.action = action
        self.action_url = action_url
        self.details = details or {}

    def _format_details(self) -> list[str]:
        """Format error-specific detail lines. Override in subclasses."""
        return [self.action]

    def __str__(self) -> str:
        """Return branded ASCII box error message."""
        return _format_error_box(
            title=self.args[0],
            lines=self._format_details(),
            action_url=self.action_url,
        )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.args[0]!r})"


class MonthlyLimitReachedError(OdysseyUsageError):
    """Monthly usage hours have been exhausted.

    The user has used all allocated hours for the current billing period.
    Usage will reset at the start of the next month.
    """

    def _format_details(self) -> list[str]:
        used = self.details.get("used_hours", "?")
        limit = self.details.get("limit_hours", "?")
        reset = self.details.get("reset_date", "next month")
        return [
            f"Used: {used} / {limit} hours",
            f"Resets: {reset}",
        ]


class ConcurrentLimitReachedError(OdysseyUsageError):
    """Too many concurrent streams are active.

    The user has reached their maximum number of simultaneous streams.
    End an existing stream to start a new one.
    """

    def _format_details(self) -> list[str]:
        active = self.details.get("active_count", "?")
        limit = self.details.get("limit", "?")
        return [
            f"Active streams: {active} / {limit}",
            "End a stream to start a new one",
        ]


class StreamDurationExceededError(OdysseyUsageError):
    """Stream exceeded maximum duration.

    The stream was automatically ended because it exceeded the
    maximum allowed duration for the user's plan.
    """

    def _format_details(self) -> list[str]:
        max_seconds = self.details.get("max_duration_seconds", 300)
        max_mins = max_seconds // 60 if isinstance(max_seconds, int) else 5
        return [
            f"Maximum stream length: {max_mins} minutes",
            "Stream was automatically ended",
        ]


class AccountSuspendedError(OdysseyUsageError):
    """Account has been suspended.

    The user's account is suspended and cannot create new streams.
    Contact support for assistance.
    """

    def _format_details(self) -> list[str]:
        reason = self.details.get("reason", "Contact support for details")
        return [
            "Your account has been suspended",
            reason,
        ]


class RateLimitError(OdysseyUsageError):
    """Too many requests in a short period.

    The user is sending requests too quickly and should slow down.
    """

    def _format_details(self) -> list[str]:
        retry_after = self.details.get("retry_after_seconds", "a few")
        return [
            f"Please wait {retry_after} seconds",
            "You are sending requests too quickly",
        ]
