class ExtractError(Exception):
    """An error whose message is safe and useful to show to the end user."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
