"""sync.py
Improved MinIO synchronisation script with URL tracking.

Features Added / Updated
------------------------
* Skips re-uploading unchanged objects (size check).
* Logs actions with `logging`.
* Generates presigned URLs for each new/changed upload (expiry set via `URL_EXPIRY`).
* Stores/updates each presigned URL in a local JSON file (`update.json` by default or `URL_JSON` env-var).
* **NEW:** Explicit logs for cron job lifecycle (start, in progress, finish).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------

load_dotenv()

ENDPOINT: str | None = os.getenv("MINIO_ENDPOINT")
ACCESS_KEY: str | None = os.getenv("MINIO_ACCESS_KEY")
SECRET_KEY: str | None = os.getenv("MINIO_SECRET_KEY")
BUCKET: str | None = os.getenv("MINIO_BUCKET")
MEDIA_DIR: str | None = os.getenv("MEDIA_DIR")
URL_EXPIRY: int = int(os.getenv("URL_EXPIRY", "3600"))  # seconds
URL_JSON: str = os.getenv("URL_JSON", "update.json")

# Basic validation ----------------------------------------------------------------

def _missing(var: Optional[str], name: str) -> None:
    if not var:
        logging.error("Environment variable %s is missing. Aborting.", name)
        sys.exit(1)

_missing(ENDPOINT, "MINIO_ENDPOINT")
_missing(ACCESS_KEY, "MINIO_ACCESS_KEY")
_missing(SECRET_KEY, "MINIO_SECRET_KEY")
_missing(BUCKET, "MINIO_BUCKET")
_missing(MEDIA_DIR, "MEDIA_DIR")

media_path = Path(MEDIA_DIR).expanduser().resolve()
if not media_path.is_dir():
    logging.error("MEDIA_DIR path %s does not exist or is not a directory", media_path)
    sys.exit(1)

json_path = Path(URL_JSON).expanduser().resolve()

# Logging -------------------------------------------------------------------------

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

# MinIO / S3 client ---------------------------------------------------------------

s3 = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
)

# Ensure bucket exists ------------------------------------------------------------

try:
    s3.head_bucket(Bucket=BUCKET)
    logging.debug("Bucket %s exists.", BUCKET)
except ClientError:
    logging.info("Bucket %s not found – creating it.", BUCKET)
    try:
        s3.create_bucket(Bucket=BUCKET)
    except ClientError as e:
        logging.error("Failed to create bucket %s: %s", BUCKET, e)
        sys.exit(1)

# Helper functions ----------------------------------------------------------------

def _load_url_map() -> Dict[str, dict]:
    """Load existing JSON or return empty dict."""
    if json_path.exists():
        try:
            with json_path.open("r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception as exc:  # noqa: broad-except
            logging.warning("Could not read %s: %s – starting fresh", json_path, exc)
    return {}


def _save_url_map(data: Dict[str, dict]) -> None:
    tmp = json_path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, indent=2)
    tmp.replace(json_path)


url_map: Dict[str, dict] = _load_url_map()


def _needs_upload(local_file: Path, key: str) -> bool:
    """Return True if the object is absent or size differs."""
    try:
        obj = s3.head_object(Bucket=BUCKET, Key=key)
        remote_size = obj["ContentLength"]
        local_size = local_file.stat().st_size
        if remote_size == local_size:
            logging.debug("Skipping unchanged file %s", key)
            return False
        logging.info(
            "File %s changed (size mismatch – local %s / remote %s)",
            key, local_size, remote_size,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "404":
            logging.warning("Could not stat remote object %s: %s", key, e)
    return True


def _upload(local_file: Path, key: str) -> None:
    """Upload a single file, generate URL, and update JSON map."""
    try:
        s3.upload_file(str(local_file), BUCKET, key)
        logging.info("Uploaded %s -> %s/%s", local_file.name, BUCKET, key)
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET, "Key": key},
            ExpiresIn=URL_EXPIRY,
        )
        logging.info("Presigned URL (valid %ss): %s", URL_EXPIRY, url)
        # Record into map
        url_map[key] = {
            "url": url,
            "expires_in": URL_EXPIRY,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        _save_url_map(url_map)
    except ClientError as e:
        logging.error("Upload failed for %s: %s", local_file, e)


# Main sync loop ------------------------------------------------------------------

if __name__ == "__main__":
    start_ts = datetime.now(timezone.utc).isoformat()
    logging.info("=== Cron job started at %s ===", start_ts)

    file_count = 0
    for path in media_path.rglob("*"):
        if path.is_file():
            file_count += 1
            key = str(path.relative_to(media_path)).replace(os.sep, "/")
            if _needs_upload(path, key):
                logging.info("Processing %s (%d)", key, file_count)
                _upload(path, key)
            else:
                logging.debug("No upload needed for %s", key)

            # heartbeat log every N files
            if file_count % 10 == 0:
                logging.info("In progress... processed %d files so far", file_count)

    logging.info("Sync finished. Processed %d files. URLs stored in %s", file_count, json_path)
    end_ts = datetime.now(timezone.utc).isoformat()
    logging.info("=== Cron job finished at %s ===", end_ts)
