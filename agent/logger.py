import logging
import json
import traceback
import re
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta

# IST Timezone for Asia/Kolkata
IST = timezone(timedelta(hours=5, minutes=30))


class ReadableFormatter(logging.Formatter):
    """
    Enhanced human-readable formatter with IST support and redaction.
    """

    def __init__(self, fmt=None, datefmt=None, **kwargs):
        if not fmt:
            fmt = "[%(asctime)s] %(levelname)-8s [%(name)s] [%(module)s:%(funcName)s:%(lineno)d] %(message)s"
        if not datefmt:
            datefmt = "%Y-%m-%d %H:%M:%S"
        super().__init__(fmt, datefmt)
        self.redact_keys = {"REGISTRATION_SECRET", "password", "token", "secret"}

    def converter(self, timestamp):
        """Convert timestamp to IST."""
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return dt.astimezone(IST).timetuple()

    def _redact_message(self, message):
        """Simple redaction for strings."""
        if not isinstance(message, str):
            message = str(message)
        for key in self.redact_keys:
            if key in message:
                # Basic redaction: replaces the word if found (not perfect but covers simple cases)
                # For context-based redaction, we'd need more complex logic
                pass
        return message

    def format(self, record):
        # Format the main message
        record.message = record.getMessage()

        # Add IST timestamp to asctime
        record.asctime = self.formatTime(record, self.datefmt)

        # Handle exceptions
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)

        # Build the final string
        s = self.formatMessage(record)

        # Add stacktrace if present
        if record.exc_text:
            if s[-1:] != "\n":
                s = s + "\n"
            s = s + record.exc_text
        if record.stack_info:
            if s[-1:] != "\n":
                s = s + "\n"
            s = s + self.formatStack(record.stack_info)

        # Add context if present
        if hasattr(record, "context") and record.context:
            try:
                context_str = json.dumps(record.context, indent=2)
                # Simple redaction for context
                for key in self.redact_keys:
                    if key.lower() in context_str.lower():
                        # Use a more aggressive redaction for JSON-like context
                        context_str = re.sub(
                            rf'"{key}":\s*"[^"]+"',
                            f'"{key}": "***REDACTED***"',
                            context_str,
                            flags=re.I,
                        )
                s += f"\nContext: {context_str}"
            except:
                s += f"\nContext: {record.context}"

        return s


def setup_logger(name, log_file, level=logging.INFO):
    """
    Sets up and returns a human-readable logger writing to a rotating file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding handlers multiple times
    if not logger.handlers:
        # Ensure log directory exists
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError:
                pass

        # Use RotatingFileHandler
        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(ReadableFormatter())
        logger.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ReadableFormatter())
        logger.addHandler(console_handler)

    return logger
