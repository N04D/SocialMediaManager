class YouTubeChannelError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.user_message = message
        self.details = details or {}
