from datetime import UTC, datetime, timedelta
from io import BytesIO
import sqlite3

from spaces_sqlite_sync import SyncConfig, download_sqlite, upload_sqlite_replace


class FakeS3Client:
    def __init__(self, download_body: bytes = b"") -> None:
        self.download_body = download_body
        self.put_calls = []
        self.copy_calls = []
        self.delete_calls = []
        now = datetime.now(UTC)
        self.objects = [
            {
                "Key": f"backups/db/wellness.db.{index}.bak",
                "LastModified": now - timedelta(days=index),
            }
            for index in range(5)
        ]

    def get_object(self, **_kwargs):
        return {"Body": BytesIO(self.download_body)}

    def copy_object(self, **kwargs):
        self.copy_calls.append(kwargs)

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)

    def list_objects_v2(self, **_kwargs):
        return {"Contents": self.objects, "IsTruncated": False}

    def delete_object(self, **kwargs):
        self.delete_calls.append(kwargs)


class FakeSpaces:
    bucket = "test-bucket"

    def __init__(self, client: FakeS3Client) -> None:
        self.client = client

    def public_url(self, key: str) -> str:
        return f"https://example.test/{key}"


def test_download_replaces_database_and_removes_sidecars(tmp_path):
    database_path = tmp_path / "wellness.db"
    database_path.write_bytes(b"old")
    database_path.with_name("wellness.db-wal").write_bytes(b"old wal")
    database_path.with_name("wellness.db-shm").write_bytes(b"old shm")
    spaces = FakeSpaces(FakeS3Client(download_body=b"new database"))

    download_sqlite(spaces, SyncConfig(key="db/wellness.db", path=database_path))

    assert database_path.read_bytes() == b"new database"
    assert not database_path.with_name("wellness.db-wal").exists()
    assert not database_path.with_name("wellness.db-shm").exists()


def test_upload_uses_snapshot_and_prunes_historical_copies(tmp_path):
    database_path = tmp_path / "wellness.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE checks (value TEXT)")
        connection.execute("INSERT INTO checks VALUES ('present')")

    client = FakeS3Client()
    spaces = FakeSpaces(client)
    config = SyncConfig(
        key="db/wellness.db",
        path=database_path,
        backup_prefix="backups",
        backup_retention=3,
    )

    url = upload_sqlite_replace(spaces, config)

    uploaded_path = tmp_path / "uploaded.db"
    uploaded_path.write_bytes(client.put_calls[0]["Body"])
    with sqlite3.connect(uploaded_path) as connection:
        assert connection.execute("SELECT value FROM checks").fetchone() == ("present",)
    assert url == "https://example.test/db/wellness.db"
    assert len(client.copy_calls) == 1
    assert [call["Key"] for call in client.delete_calls] == [
        "backups/db/wellness.db.3.bak",
        "backups/db/wellness.db.4.bak",
    ]
