class BCTError(RuntimeError):
    code = "BCT_ERROR"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.code)


class AuthorizationError(BCTError):
    code = "AUTHORIZATION_DENIED"


class ConflictError(BCTError):
    code = "RESOURCE_CONFLICT"


class PreconditionError(BCTError):
    code = "PRECONDITION_FAILED"


class UnknownEffectError(BCTError):
    code = "EFFECT_UNKNOWN"

    def __init__(self, message: str | None = None, *, release_claims: bool = False):
        super().__init__(message)
        self.release_claims = release_claims


class ConfirmedFailure(BCTError):
    code = "EXECUTION_FAILED"

    def __init__(self, message: str | None = None, *, release_claims: bool = False):
        super().__init__(message)
        self.release_claims = release_claims
