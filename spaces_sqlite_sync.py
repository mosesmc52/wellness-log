#!/usr/bin/env python3
"""
spaces_sqlite_sync.py

Download a SQLite database from DigitalOcean Spaces to a local path
and/or upload it back to replace the same object key.

Examples:
  # Download from Spaces to local file
  python spaces_sqlite_sync.py download --key db/portfolio.sqlite --path ./data/portfolio.sqlite

  # Upload local file to Spaces (replace object)
  python spaces_sqlite_sync.py upload --key db/portfolio.sqlite --path ./data/portfolio.sqlite

  # Download then upload (round trip / "sync" style)
  python spaces_sqlite_sync.py sync --key db/portfolio.sqlite --path ./data/portfolio.sqlite

Environment (preferred):
  SPACES_KEY, SPACES_SECRET, SPACES_BUCKET
  SPACES_REGION (default nyc3)
  SPACES_ENDPOINT (optional)
  SPACES_CDN_BASE (optional)
  SPACES_DB_KEY (default db/wellness.db)
  SPACES_DB_PATH (default ./data/wellness.db)
  SPACES_BACKUP_PREFIX (default backups)
  SPACES_BACKUP_RETENTION (default 3)

Notes:
- Uses SpacesClient.client (boto3 S3 client) for get_object/put_object with explicit Key.
- Upload uses multipart-safe single put; for very large DBs, consider multipart upload.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

SQLITE_CONTENT_TYPES = {
    ".sqlite": "application/x-sqlite3",
    ".db": "application/x-sqlite3",
    ".sqlite3": "application/x-sqlite3",
}


class SpacesClient:
    """Minimal DigitalOcean Spaces client backed by boto3's S3 API."""

    def __init__(self) -> None:
        missing = [
            name
            for name in ("SPACES_KEY", "SPACES_SECRET", "SPACES_BUCKET")
            if not os.getenv(name)
        ]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self.bucket = os.environ["SPACES_BUCKET"]
        self.region = os.getenv("SPACES_REGION", "nyc3")
        self.endpoint = os.getenv("SPACES_ENDPOINT") or (
            f"https://{self.region}.digitaloceanspaces.com"
        )
        self.cdn_base = os.getenv("SPACES_CDN_BASE")
        self.client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint,
            aws_access_key_id=os.environ["SPACES_KEY"],
            aws_secret_access_key=os.environ["SPACES_SECRET"],
        )

    def public_url(self, key: str) -> str:
        encoded_key = quote(key.lstrip("/"), safe="/")
        if self.cdn_base:
            return f"{self.cdn_base.rstrip('/')}/{encoded_key}"
        return f"https://{self.bucket}.{self.region}.digitaloceanspaces.com/{encoded_key}"


@dataclass
class SyncConfig:
    key: str
    path: Path
    acl: str = (
        "private"  # prefer private for DBs; use "public-read" only if you truly want it public
    )
    backup_prefix: Optional[str] = "backups"
    backup_retention: int = 3
    overwrite_local: bool = True
    make_dirs: bool = True


def _guess_content_type(p: Path) -> str:
    return SQLITE_CONTENT_TYPES.get(p.suffix.lower(), "application/octet-stream")


def _ensure_parent_dir(path: Path) -> None:
    parent = path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)


def _read_consistent_sqlite(path: Path) -> bytes:
    """Read a consistent snapshot, including committed data still in the WAL."""
    file_descriptor, snapshot_name = tempfile.mkstemp(suffix=path.suffix)
    os.close(file_descriptor)
    snapshot_path = Path(snapshot_name)
    source = destination = None
    try:
        source = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=30)
        destination = sqlite3.connect(snapshot_path)
        source.backup(destination)
        destination.close()
        destination = None
        source.close()
        source = None
        return snapshot_path.read_bytes()
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        snapshot_path.unlink(missing_ok=True)


def _prune_backups(spaces: SpacesClient, cfg: SyncConfig) -> None:
    if not cfg.backup_prefix or cfg.backup_retention < 0:
        return

    history_prefix = (
        f"{cfg.backup_prefix.rstrip('/')}/{cfg.key.lstrip('/')}."
    )
    objects: list[dict] = []
    continuation_token: str | None = None
    while True:
        request = {"Bucket": spaces.bucket, "Prefix": history_prefix}
        if continuation_token:
            request["ContinuationToken"] = continuation_token
        response = spaces.client.list_objects_v2(**request)
        objects.extend(response.get("Contents", []))
        if not response.get("IsTruncated"):
            break
        continuation_token = response["NextContinuationToken"]

    objects.sort(
        key=lambda item: (item.get("LastModified"), item["Key"]), reverse=True
    )
    for stale in objects[cfg.backup_retention :]:
        spaces.client.delete_object(Bucket=spaces.bucket, Key=stale["Key"])
        print(f"Deleted expired backup: s3://{spaces.bucket}/{stale['Key']}")


def download_sqlite(spaces: SpacesClient, cfg: SyncConfig) -> Path:
    if cfg.make_dirs:
        _ensure_parent_dir(cfg.path)

    if cfg.path.exists() and not cfg.overwrite_local:
        raise FileExistsError(f"Local file exists and overwrite disabled: {cfg.path}")

    try:
        resp = spaces.client.get_object(Bucket=spaces.bucket, Key=cfg.key)
    except ClientError as e:
        raise RuntimeError(
            f"Failed to download s3://{spaces.bucket}/{cfg.key}: {e}"
        ) from e

    body = resp["Body"].read()

    # Basic guard: avoid writing empty file unless object truly empty
    if not body:
        raise RuntimeError(
            f"Downloaded object is empty: s3://{spaces.bucket}/{cfg.key}"
        )

    temporary_path = cfg.path.with_name(f".{cfg.path.name}.download")
    try:
        temporary_path.write_bytes(body)
        temporary_path.replace(cfg.path)
    finally:
        temporary_path.unlink(missing_ok=True)

    # A restored main database must not reuse sidecars from the previous file.
    for suffix in ("-wal", "-shm"):
        cfg.path.with_name(f"{cfg.path.name}{suffix}").unlink(missing_ok=True)

    return cfg.path


def upload_sqlite_replace(spaces: SpacesClient, cfg: SyncConfig) -> str:
    if not cfg.path.exists():
        raise FileNotFoundError(f"Local SQLite not found: {cfg.path}")

    data = _read_consistent_sqlite(cfg.path)
    if not data:
        raise RuntimeError(f"Local file is empty; refusing to upload: {cfg.path}")

    content_type = _guess_content_type(cfg.path)

    # Optional: create a backup copy in Spaces before replacing
    if cfg.backup_prefix:
        backup_key = f"{cfg.backup_prefix.rstrip('/')}/{cfg.key.lstrip('/')}.{int(time.time())}.bak"
        try:
            spaces.client.copy_object(
                Bucket=spaces.bucket,
                CopySource={"Bucket": spaces.bucket, "Key": cfg.key},
                Key=backup_key,
                ACL=cfg.acl,
                ContentType=content_type,
                MetadataDirective="REPLACE",
            )
            print(f"Backup created: s3://{spaces.bucket}/{backup_key}")
        except ClientError as e:
            # If original doesn't exist yet, backup can fail; that's okay
            code = getattr(e, "response", {}).get("Error", {}).get("Code")
            if code not in ("NoSuchKey", "404"):
                raise RuntimeError(f"Failed to backup existing object: {e}") from e
            print(
                "No existing object to backup (or not accessible). Continuing with upload..."
            )

    try:
        spaces.client.put_object(
            Bucket=spaces.bucket,
            Key=cfg.key,
            Body=data,
            ACL=cfg.acl,
            ContentType=content_type,
        )
    except ClientError as e:
        raise RuntimeError(
            f"Failed to upload (replace) s3://{spaces.bucket}/{cfg.key}: {e}"
        ) from e

    _prune_backups(spaces, cfg)

    # Return a URL only if you have CDN base or public endpoint; for private ACL this is not directly fetchable
    return spaces.public_url(cfg.key)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Download/upload (replace) a SQLite file to DigitalOcean Spaces."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(sp):
        sp.add_argument(
            "--key",
            default=os.getenv("SPACES_DB_KEY", "db/wellness.db"),
            help="Spaces object key (default: SPACES_DB_KEY or db/wellness.db)",
        )
        sp.add_argument(
            "--path",
            default=os.getenv("SPACES_DB_PATH", "./data/wellness.db"),
            help="Local SQLite path (default: SPACES_DB_PATH or ./data/wellness.db)",
        )
        sp.add_argument(
            "--acl",
            default="private",
            help='Object ACL (default "private"; use "public-read" if needed)',
        )
        sp.add_argument(
            "--backup-prefix",
            default=os.getenv("SPACES_BACKUP_PREFIX", "backups"),
            help="Historical-copy prefix (default: SPACES_BACKUP_PREFIX or backups)",
        )
        sp.add_argument(
            "--backup-retention",
            type=int,
            default=int(os.getenv("SPACES_BACKUP_RETENTION", "3")),
            help="Maximum historical copies to retain (default: 3)",
        )

    sp_download = sub.add_parser(
        "download", help="Download object from Spaces to local path"
    )
    add_common(sp_download)
    sp_download.add_argument(
        "--no-overwrite-local",
        action="store_true",
        help="If set, refuse to overwrite local file if it already exists",
    )

    sp_upload = sub.add_parser(
        "upload", help="Upload local file to Spaces (replace object key)"
    )
    add_common(sp_upload)

    sp_sync = sub.add_parser(
        "sync", help="Download then upload (useful for round-trip verification)"
    )
    add_common(sp_sync)
    sp_sync.add_argument(
        "--no-overwrite-local",
        action="store_true",
        help="If set, refuse to overwrite local file if it already exists",
    )

    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    cfg = SyncConfig(
        key=args.key,
        path=Path(args.path).expanduser().resolve(),
        acl=args.acl,
        backup_prefix=getattr(args, "backup_prefix", None),
        backup_retention=getattr(args, "backup_retention", 3),
        overwrite_local=not getattr(args, "no_overwrite_local", False),
    )

    spaces = SpacesClient()  # reads env vars by default

    if args.cmd == "download":
        out = download_sqlite(spaces, cfg)
        print(f"Downloaded to: {out}")
        return 0

    if args.cmd == "upload":
        url = upload_sqlite_replace(spaces, cfg)
        print(f"Uploaded (replaced): s3://{spaces.bucket}/{cfg.key}")
        print(f"URL (may require auth if private): {url}")
        return 0

    if args.cmd == "sync":
        out = download_sqlite(spaces, cfg)
        print(f"Downloaded to: {out}")
        url = upload_sqlite_replace(spaces, cfg)
        print(f"Uploaded (replaced): s3://{spaces.bucket}/{cfg.key}")
        print(f"URL (may require auth if private): {url}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
