"""Exception classes for the Odyssey client library."""


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
