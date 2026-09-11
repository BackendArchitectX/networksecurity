from __future__ import annotations

import sys
from types import ModuleType


class NetworkSecurityException(Exception):
    """Adds source context while preserving the original exception as the cause."""

    def __init__(self, error_message: Exception | str, error_details: ModuleType | None = None):
        super().__init__(str(error_message))
        self.error_message = str(error_message)
        self.file_name: str | None = None
        self.line_number: int | None = None

        details = error_details or sys
        _, _, exc_tb = details.exc_info()
        if exc_tb is not None:
            self.line_number = exc_tb.tb_lineno
            self.file_name = exc_tb.tb_frame.f_code.co_filename

    def __str__(self) -> str:
        if self.file_name is None or self.line_number is None:
            return self.error_message
        return f"{self.file_name}:{self.line_number}: {self.error_message}"
