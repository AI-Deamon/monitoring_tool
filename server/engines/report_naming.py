"""
server/engines/report_naming.py — Centralized report filename generation,
parsing, export metadata, and collision-safe file handling for SentinelEdge.

Standard filename structure:
  <identity>_<report_type>_<period>_generated-<timestamp>_<export_id>.<ext>

Examples:
  desktop-abc_daily_2026-10-12_generated-20261012T091532Z_a81f2c.pdf
  desktop-abc_daily_2026-10-12_generated-20261012T184207Z_f29b61.pdf
  team_weekly_2026-10-05_to_2026-10-11_generated-20261012T091532Z_b81d32.pdf
  team_monthly_2026-09-01_to_2026-09-30_generated-20261012T091532Z_c45e67.pdf
"""

import os
import re
import uuid
import shutil
import logging
import unicodedata
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, Union

logger = logging.getLogger(__name__)

# Base storage directory for persistent exports (configurable via REPORT_STORAGE_DIR)
DEFAULT_STORAGE_DIR = Path(__file__).resolve().parent.parent / "reports"


def get_reports_storage_dir() -> Path:
    """Return the configured or default report exports directory, ensuring it exists."""
    env_dir = os.environ.get("REPORT_STORAGE_DIR")
    storage_path = Path(env_dir) if env_dir else DEFAULT_STORAGE_DIR
    storage_path.mkdir(parents=True, exist_ok=True)
    return storage_path


def sanitize_identity(identity: Optional[str], default: str = "agent") -> str:
    """
    Sanitize an agent or entity identity into a clean, filesystem-safe string:
    - Lowercase alphanumeric characters, hyphens, and underscores.
    - Replaces whitespace, punctuation, slashes, and separators with a single hyphen.
    - Strips leading and trailing hyphens.
    - Normalizes unicode accents (e.g. 'René' -> 'rene').
    - Returns `default` if the resulting string is empty or None.
    """
    if not identity:
        return default.strip().lower() or "agent"

    # Normalize unicode to ASCII
    text = unicodedata.normalize("NFKD", str(identity))
    text = text.encode("ascii", "ignore").decode("ascii")

    # Lowercase
    text = text.lower().strip()

    # Replace invalid chars with hyphen
    text = re.sub(r"[^a-z0-9_-]+", "-", text)

    # Collapse multiple consecutive hyphens
    text = re.sub(r"-+", "-", text)

    # Strip leading/trailing hyphens or underscores
    text = text.strip("-_")

    return text if text else default.strip().lower() or "agent"


def _format_date(val: Union[date, datetime, str]) -> str:
    """Format date, datetime, or ISO string as YYYY-MM-DD."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    # If string contains time (e.g. 2026-10-12T09:00:00), take date part
    if "T" in s:
        s = s.split("T")[0]
    elif " " in s:
        s = s.split(" ")[0]
    return s


def format_period(report_type: str, start_date: Union[date, datetime, str], end_date: Optional[Union[date, datetime, str]] = None) -> str:
    """
    Format reporting period:
    - Daily: YYYY-MM-DD
    - Weekly/Monthly or date range: YYYY-MM-DD_to_YYYY-MM-DD
    """
    start_str = _format_date(start_date)
    end_str = _format_date(end_date) if end_date else start_str

    if report_type == "daily" or start_str == end_str:
        return start_str
    return f"{start_str}_to_{end_str}"


def generate_export_id(length: int = 6) -> str:
    """Generate a unique hex export identifier."""
    return uuid.uuid4().hex[:max(4, length)]


def format_generation_timestamp(dt: Optional[Union[datetime, str]] = None) -> str:
    """
    Format a UTC generation timestamp as YYYYMMDDTHHMMSSZ.
    """
    if dt is None:
        utc_now = datetime.now(timezone.utc)
        return utc_now.strftime("%Y%m%dT%H%M%SZ")
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y%m%dT%H%M%SZ")
    s = str(dt).strip()
    # If already in YYYYMMDDTHHMMSSZ format
    if re.match(r"^\d{8}T\d{6}Z$", s):
        return s
    try:
        parsed = datetime.fromisoformat(s)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc)
        return parsed.strftime("%Y%m%dT%H%M%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_report_filename(
    report_type: str,
    scope: str = "individual",
    identity: Optional[str] = None,
    start_date: Optional[Union[date, datetime, str]] = None,
    end_date: Optional[Union[date, datetime, str]] = None,
    generated_at: Optional[Union[datetime, str]] = None,
    export_id: Optional[str] = None,
    ext: str = "pdf",
) -> str:
    """
    Construct standardized report filename:
      <identity>_<report_type>_<period>_generated-<timestamp>_<export_id>.<ext>
    """
    # 1. Identity
    if scope == "team":
        safe_identity = "team"
    else:
        safe_identity = sanitize_identity(identity, default="agent")

    # 2. Report type (daily, weekly, monthly)
    safe_type = sanitize_identity(report_type, default="report")

    # 3. Period
    if start_date is None:
        start_date = date.today()
    period = format_period(safe_type, start_date, end_date)

    # 4. Generation timestamp
    ts_str = format_generation_timestamp(generated_at)

    # 5. Export ID
    eid = (export_id or generate_export_id()).lower()

    # 6. Extension
    clean_ext = ext.lstrip(".") if ext else "pdf"

    return f"{safe_identity}_{safe_type}_{period}_generated-{ts_str}_{eid}.{clean_ext}"


def build_report_metadata(
    report_type: str,
    scope: str = "individual",
    identity: Optional[str] = None,
    start_date: Optional[Union[date, datetime, str]] = None,
    end_date: Optional[Union[date, datetime, str]] = None,
    generated_at: Optional[Union[datetime, str]] = None,
    export_id: Optional[str] = None,
    ext: str = "pdf",
    file_path: Optional[str] = None,
    status: str = "completed",
) -> Dict[str, Any]:
    """
    Build structured metadata dictionary for an export record.
    """
    if scope == "team":
        safe_identity = "team"
    else:
        safe_identity = sanitize_identity(identity, default="agent")

    safe_type = sanitize_identity(report_type, default="report")
    if start_date is None:
        start_date = date.today()
    s_date = _format_date(start_date)
    e_date = _format_date(end_date) if end_date else s_date
    period = format_period(safe_type, s_date, e_date)
    ts_str = format_generation_timestamp(generated_at)
    eid = (export_id or generate_export_id()).lower()
    clean_ext = ext.lstrip(".") if ext else "pdf"
    filename = f"{safe_identity}_{safe_type}_{period}_generated-{ts_str}_{eid}.{clean_ext}"

    return {
        "export_id": eid,
        "report_type": safe_type,
        "scope": scope,
        "identity": safe_identity,
        "raw_identity": identity,
        "period": period,
        "start_date": s_date,
        "end_date": e_date,
        "generated_at": ts_str,
        "filename": filename,
        "extension": clean_ext,
        "file_path": file_path,
        "status": status,
    }


def parse_report_filename(filename: str) -> Dict[str, Any]:
    """
    Parse a report filename into its component metadata fields.
    Supports both new structured filenames and legacy filenames.
    """
    name = Path(filename).name
    ext = Path(filename).suffix.lstrip(".")

    # Regex for new format:
    # <identity>_<report_type>_<period>_generated-<timestamp>_<export_id>.<ext>
    # where period can be YYYY-MM-DD or YYYY-MM-DD_to_YYYY-MM-DD
    new_pattern = re.compile(
        r"^(?P<identity>.+?)_(?P<report_type>daily|weekly|monthly)_(?P<period>\d{4}-\d{2}-\d{2}(?:_to_\d{4}-\d{2}-\d{2})?)_generated-(?P<timestamp>\d{8}T\d{6}Z)_(?P<export_id>[a-f0-9]+)\.(?P<ext>[a-zA-Z0-9]+)$",
        re.IGNORECASE,
    )
    m = new_pattern.match(name)
    if m:
        data = m.groupdict()
        period = data["period"]
        if "_to_" in period:
            start_date, end_date = period.split("_to_")
        else:
            start_date, end_date = period, period

        identity = data["identity"]
        scope = "team" if identity.lower() == "team" else "individual"
        return {
            "is_legacy": False,
            "filename": name,
            "identity": identity,
            "scope": scope,
            "report_type": data["report_type"].lower(),
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "generated_at": data["timestamp"],
            "export_id": data["export_id"].lower(),
            "extension": data["ext"].lower(),
        }

    # Legacy team weekly format: team_weekly_YYYY-MM-DD_to_YYYY-MM-DD.<ext>
    legacy_team_weekly = re.match(
        r"^team_weekly_(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})\.(?P<ext>[a-zA-Z0-9]+)$",
        name,
        re.IGNORECASE,
    )
    if legacy_team_weekly:
        d = legacy_team_weekly.groupdict()
        return {
            "is_legacy": True,
            "filename": name,
            "identity": "team",
            "scope": "team",
            "report_type": "weekly",
            "period": f"{d['start']}_to_{d['end']}",
            "start_date": d["start"],
            "end_date": d["end"],
            "generated_at": None,
            "export_id": None,
            "extension": d["ext"].lower(),
        }

    # Legacy individual weekly format: <user>_weekly_YYYY-MM-DD_to_YYYY-MM-DD.<ext>
    legacy_user_weekly = re.match(
        r"^(?P<user>.+?)_weekly_(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})\.(?P<ext>[a-zA-Z0-9]+)$",
        name,
        re.IGNORECASE,
    )
    if legacy_user_weekly:
        d = legacy_user_weekly.groupdict()
        return {
            "is_legacy": True,
            "filename": name,
            "identity": sanitize_identity(d["user"]),
            "scope": "individual",
            "report_type": "weekly",
            "period": f"{d['start']}_to_{d['end']}",
            "start_date": d["start"],
            "end_date": d["end"],
            "generated_at": None,
            "export_id": None,
            "extension": d["ext"].lower(),
        }

    # Legacy daily format: <user>_daily_YYYY-MM-DD.<ext>
    legacy_daily = re.match(
        r"^(?P<user>.+?)_daily_(?P<date>\d{4}-\d{2}-\d{2})\.(?P<ext>[a-zA-Z0-9]+)$",
        name,
        re.IGNORECASE,
    )
    if legacy_daily:
        d = legacy_daily.groupdict()
        identity = sanitize_identity(d["user"])
        scope = "team" if identity == "team" else "individual"
        return {
            "is_legacy": True,
            "filename": name,
            "identity": identity,
            "scope": scope,
            "report_type": "daily",
            "period": d["date"],
            "start_date": d["date"],
            "end_date": d["date"],
            "generated_at": None,
            "export_id": None,
            "extension": d["ext"].lower(),
        }

    # Legacy team monthly format: team_monthly_YYYY-MM-DD_to_YYYY-MM-DD.<ext>
    legacy_monthly = re.match(
        r"^(?P<user>.+?)_monthly_(?P<start>\d{4}-\d{2}-\d{2})_to_(?P<end>\d{4}-\d{2}-\d{2})\.(?P<ext>[a-zA-Z0-9]+)$",
        name,
        re.IGNORECASE,
    )
    if legacy_monthly:
        d = legacy_monthly.groupdict()
        identity = sanitize_identity(d["user"])
        scope = "team" if identity == "team" else "individual"
        return {
            "is_legacy": True,
            "filename": name,
            "identity": identity,
            "scope": scope,
            "report_type": "monthly",
            "period": f"{d['start']}_to_{d['end']}",
            "start_date": d["start"],
            "end_date": d["end"],
            "generated_at": None,
            "export_id": None,
            "extension": d["ext"].lower(),
        }

    # Fallback unknown format
    return {
        "is_legacy": True,
        "filename": name,
        "identity": "unknown",
        "scope": "unknown",
        "report_type": "unknown",
        "period": "unknown",
        "start_date": None,
        "end_date": None,
        "generated_at": None,
        "export_id": None,
        "extension": ext,
    }


def resolve_collision_safe_path(target_path: Union[str, Path]) -> Path:
    """
    Ensure the target path does not overwrite an existing file.
    If target_path exists, appends a new unique suffix before the extension.
    """
    p = Path(target_path)
    if not p.exists():
        return p

    parent = p.parent
    stem = p.stem
    ext = p.suffix

    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{ext}"
        if not candidate.exists():
            return candidate
        counter += 1


def safe_write_file(
    content: Union[str, bytes, Path],
    target_path: Union[str, Path, bytes, None] = None,
    encoding: str = "utf-8",
) -> Path:
    """
    Safely write content to target_path using an atomic temp file:
    - Writes to a `.tmp.<uuid>` file first.
    - Resolves collision to ensure no existing file is overwritten.
    - Atomically renames to the destination.
    - Cleans up incomplete temp file on any exception.
    """
    # Auto-detect swapped arguments if called as safe_write_file(target_path, content)
    if isinstance(content, Path) or (
        isinstance(content, str)
        and isinstance(target_path, (str, bytes))
        and ("\\" in content or "/" in content or content.endswith((".html", ".pdf", ".csv", ".txt")))
    ):
        content, target_path = target_path, content

    dest = resolve_collision_safe_path(target_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = dest.parent / f"{dest.name}.tmp.{uuid.uuid4().hex[:6]}"
    try:
        if isinstance(content, str):
            with open(tmp_path, "w", encoding=encoding) as f:
                f.write(content)
        else:
            with open(tmp_path, "wb") as f:
                f.write(content)

        # Verify non-empty write
        if tmp_path.stat().st_size == 0 and len(content) > 0:
            raise IOError(f"Written file is empty: {tmp_path}")

        # Atomic move / replace
        shutil.move(str(tmp_path), str(dest))
        return dest
    except Exception as e:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass
        raise e
