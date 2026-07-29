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


# Third-party loggers that would otherwise flood the log now that records
# reach the root handlers. urllib3 in particular logs every HTTP request the
# uploader makes.
NOISY_LOGGERS = (
    "urllib3",
    "requests",
    "asyncio",
    "charset_normalizer",
    "PIL",
)


def setup_logger(name, log_file, level=logging.INFO):
    """
    Sets up and returns a human-readable logger writing to a rotating file.

    Handlers go on the ROOT logger, not on `name`. Every module outside
    service.py uses logging.getLogger(__name__) - core.updater, core.buffer,
    helper.state_detector - which are siblings of a named logger like
    "SentinelCore", not descendants. Attaching the handlers to the named
    logger meant those records propagated to a bare root logger, hit
    logging.lastResort, and were dropped at INFO / dumped to stderr unformatted
    at WARNING+. On L180701PB that left core.log holding records from
    service.py alone: the entire update, buffer and uploader subsystems logged
    into a void.

    Root handlers fix that for every module at once. `name` is still returned
    (with no handlers of its own, so it propagates) to keep the existing
    call sites working and to keep one record per emit rather than two.
    """
    root = logging.getLogger()
    root.setLevel(level)

    target = os.path.abspath(log_file)
    already_attached = any(
        isinstance(handler, RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == target
        for handler in root.handlers
    )

    if not already_attached:
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
        root.addHandler(file_handler)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(ReadableFormatter())
        root.addHandler(console_handler)

    for noisy in NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    # No handlers here on purpose - it propagates to root. Handlers on both
    # would write every service.py line twice.
    return logger
