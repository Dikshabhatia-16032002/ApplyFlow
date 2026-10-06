class AppError(Exception):
    def __init__(self, status_code: int, code: str, detail: str, **extra: object) -> None:
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


def not_found(noun: str) -> AppError:
    return AppError(404, "not_found", f"{noun} not found")
