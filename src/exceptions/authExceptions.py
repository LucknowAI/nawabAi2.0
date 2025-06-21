class AuthException(Exception):
    """Base authentication exception."""
    pass

class InvalidCredentialsException(AuthException):
    """Invalid credentials provided."""
    pass

class TokenExpiredException(AuthException):
    """Token has expired."""
    pass

class AccountLockedException(AuthException):
    """Account is locked."""
    pass
