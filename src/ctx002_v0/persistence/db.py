from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .reason_binding import ReasonCodeBinding, validate_reason_code_binding

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path


class MigrationValidationError(RuntimeError):
    pass


class MigrationChecksumMismatchError(MigrationValidationError):
    pass


class DirtyMigrationError(MigrationValidationError):
    pass


def connect_sqlite(db_path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def enforce_foreign_keys(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")
    enabled = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if enabled != 1:
        raise MigrationValidationError("FK_PRAGMA_ENFORCEMENT_FAILED")


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL,
            dirty INTEGER NOT NULL DEFAULT 0 CHECK (dirty IN (0, 1))
        )
        """
    )


def discover_migrations(migrations_dir: Path = DEFAULT_MIGRATIONS_DIR) -> list[Migration]:
    if not migrations_dir.exists():
        return []

    entries = [p for p in migrations_dir.iterdir() if p.is_file() and p.suffix == ".sql"]
    ordered = sorted(entries, key=lambda p: p.name)
    return [Migration(version=p.stem, path=p) for p in ordered]


def migration_checksum(sql_text: str) -> str:
    normalized = sql_text.replace("\r\n", "\n").replace("\r", "\n")
    return sha256(normalized.encode("utf-8")).hexdigest()


def fail_if_dirty_migration(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT version FROM schema_migrations WHERE dirty = 1 LIMIT 1").fetchone()
    if row:
        raise DirtyMigrationError(f"DIRTY_MIGRATION_GUARD:{row['version']}")


def verify_migration_checksums(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    fail_if_dirty_migration(conn)

    rows = conn.execute("SELECT version, checksum, dirty FROM schema_migrations").fetchall()
    expected = {m.version: migration_checksum(m.path.read_text()) for m in migrations}
    for row in rows:
        version = row["version"]
        if row["dirty"] == 1:
            raise DirtyMigrationError(f"DIRTY_MIGRATION_GUARD:{version}")
        if version in expected and expected[version] != row["checksum"]:
            raise MigrationChecksumMismatchError(f"MIGRATION_CHECKSUM_MISMATCH:{version}")


def apply_migrations(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    ensure_schema_migrations_table(conn)
    fail_if_dirty_migration(conn)

    for migration in migrations:
        sql_text = migration.path.read_text()
        checksum = migration_checksum(sql_text)
        existing = conn.execute(
            "SELECT checksum, dirty FROM schema_migrations WHERE version = ?",
            (migration.version,),
        ).fetchone()

        if existing:
            if existing["dirty"] == 1:
                raise DirtyMigrationError(f"DIRTY_MIGRATION_GUARD:{migration.version}")
            if existing["checksum"] != checksum:
                raise MigrationChecksumMismatchError(f"MIGRATION_CHECKSUM_MISMATCH:{migration.version}")
            continue

        conn.execute(
            "INSERT INTO schema_migrations(version, checksum, applied_at_utc, dirty) VALUES (?, ?, ?, 1)",
            (migration.version, checksum, "PENDING"),
        )
        conn.commit()

        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.executescript(sql_text)
            conn.execute(
                "UPDATE schema_migrations SET dirty = 0, applied_at_utc = ? WHERE version = ?",
                (datetime.now(UTC).isoformat(), migration.version),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    verify_migration_checksums(conn, migrations)


def bootstrap_database(
    db_path: str = ":memory:",
    *,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
    reason_binding: ReasonCodeBinding | None = None,
) -> sqlite3.Connection:
    conn = connect_sqlite(db_path)
    enforce_foreign_keys(conn)
    migrations = discover_migrations(migrations_dir)
    apply_migrations(conn, migrations)
    if reason_binding is not None:
        validate_reason_code_binding(reason_binding)
    return conn
