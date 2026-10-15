class PlatformError(Exception):
    """Base domain exception for the platform."""
    pass


class SessionConversionError(PlatformError):
    """Raised when parsing or converting a session fails."""
    pass


class AccountAuthError(PlatformError):
    """Raised when Telegram authentication fails for an account."""
    pass


class AccountBannedError(AccountAuthError):
    """Raised when an account is deactivated or banned."""
    pass


class AccountFloodWaitError(AccountAuthError):
    """Raised when an account receives FLOOD_WAIT from Telegram."""
    def __init__(self, seconds: int):
        super().__init__(f"FloodWait: Need to wait {seconds} seconds")
        self.seconds = seconds


class TwoFactorRequiredError(AccountAuthError):
    """Raised when 2FA password is required to complete login."""
    pass


class ProxyConnectionError(PlatformError):
    """Raised when proxy health-check or connection fails."""
    pass
