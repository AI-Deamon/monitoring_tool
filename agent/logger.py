import logging
import json
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
import os

class JSONFormatter(logging.Formatter):
    """
    Formatter that outputs JSON strings after parsing the LogRecord.
    Redacts sensitive tags.
    """
    def __init__(self, **kwargs):
        super().__init__()
        self.redact_keys = {"REGISTRATION_SECRET", "password", "token", "secret"}

    def _redact(self, data):
        """Recursively redact sensitive keys from dictionary data."""
        if isinstance(data, dict):
            return {
                k: "***REDACTED***" if any(r.lower() in k.lower() for r in self.redact_keys) else self._redact(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [self._redact(item) for item in data]
        return data

    def format(self, record):
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname.lower(),
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "funcName": record.funcName,
            "lineNo": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
            log_data["stacktrace"] = traceback.format_exc()

        # Add custom extra context fields passed in logger.info("msg", extra={"context": ...})
        if hasattr(record, "context"):
            log_data["context"] = self._redact(record.context)

        return json.dumps(log_data)

def setup_logger(name, log_file, level=logging.INFO):
    """
    Sets up and returns a structured JSON logger writing to a rotating file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding handlers multiple times if logger already exists
    if not logger.handlers:
        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError:
                pass

        # Use RotatingFileHandler to manage file sizes (e.g. 5MB per file, max 3 files)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3
        )
        file_handler.setFormatter(JSONFormatter())
        
        logger.addHandler(file_handler)
        
        # Optional: Log to stdout for development, but primarily stick to file
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(JSONFormatter())
        logger.addHandler(console_handler)

    return logger
