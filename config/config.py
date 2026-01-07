"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from dotenv import load_dotenv


def _load_dotenv() -> None:
    """Load environment variables from the project-level .env file."""

    project_root = Path(__file__).resolve().parents[1]
    dotenv_path = project_root / ".env"

    # load_dotenv silently returns False when the file is missing; environment
    # variables provided by the OS remain untouched.
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
    else:
        load_dotenv()


def _get_env(
    key: str,
    default: Optional[str] = None,
    *,
    cast: Optional[Callable[[str], Any]] = None,
    required: bool = False,
) -> Any:
    """Fetch a value from the environment with optional casting and validation."""

    value = os.getenv(key, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required environment variable: {key}")

    if value is not None and cast is not None:
        try:
            return cast(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Invalid value for {key}: {value}") from exc

    return value


_load_dotenv()

MYSQL_HOST = _get_env("MYSQL_HOST", required=True)
MYSQL_PORT = _get_env("MYSQL_PORT", default="3306", cast=int)
MYSQL_USERNAME = _get_env("MYSQL_USERNAME", required=True)
MYSQL_PASSWORD = _get_env("MYSQL_PASSWORD", required=True)
MYSQL_DATABASE = _get_env("MYSQL_DATABASE", required=True)
OSS_ENDPOINTURI = _get_env("OSS_ENDPOINTURI", required=True)
OSS_ACCESSKEYID = _get_env("OSS_ACCESSKEYID", required=True)
OSS_ACCESSKEYSECRET = _get_env("OSS_ACCESSKEYSECRET", required=True)
OSS_BUCKET = _get_env("OSS_BUCKET", required=True)
DB_CONNECTION = _get_env("DB_CONNECTION", default="mysql")
DB_HOST = _get_env("DB_HOST") or MYSQL_HOST
DB_PORT = _get_env("DB_PORT", default="3306", cast=int)
DB_DATABASE = _get_env("DB_DATABASE") or MYSQL_DATABASE
DB_USERNAME = _get_env("DB_USERNAME") or MYSQL_USERNAME
DB_PASSWORD = _get_env("DB_PASSWORD") or MYSQL_PASSWORD


THCPN_DB_CONFIG: Dict[str, Any] = {
    "MYSQL_HOST": MYSQL_HOST,
    "MYSQL_PORT": MYSQL_PORT,
    "MYSQL_USERNAME": MYSQL_USERNAME,
    "MYSQL_PASSWORD": MYSQL_PASSWORD,
    "MYSQL_DATABASE": MYSQL_DATABASE,
    "OSS_ENDPOINTURI": OSS_ENDPOINTURI,
    "OSS_ACCESSKEYID": OSS_ACCESSKEYID,
    "OSS_ACCESSKEYSECRET": OSS_ACCESSKEYSECRET,
    "OSS_BUCKET": OSS_BUCKET,
    "DB_CONNECTION": DB_CONNECTION,
    "DB_HOST": DB_HOST,
    "DB_PORT": DB_PORT,
    "DB_DATABASE": DB_DATABASE,
    "DB_USERNAME": DB_USERNAME,
    "DB_PASSWORD": DB_PASSWORD,
}

