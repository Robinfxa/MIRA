class DomainError(Exception):
    """Expected contract violation. Transport maps codes, never provider error bodies."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)
