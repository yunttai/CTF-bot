from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Iterable

from ctf_bot.models import StoredContest


DEFAULT_DB_PATH = "data/ctf_snapshot.db"


class StorageError(RuntimeError):
    """Raised when the local contest DB cannot be used."""


def resolve_db_path(path: str | None = None) -> Path:
    return Path(path or DEFAULT_DB_PATH)


class ContestRepository:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = resolve_db_path(str(db_path) if db_path is not None else None)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            self._create_schema(connection)
            connection.commit()

    def replace_snapshot(self, contests: Iterable[StoredContest], refreshed_at: datetime) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            self._create_schema(connection)
            existing_notification_state = {
                row["contest_key"]: (
                    bool(row["discord_notified"]),
                    datetime.fromisoformat(row["discord_notified_at"]) if row["discord_notified_at"] else None,
                )
                for row in connection.execute(
                    "SELECT contest_key, discord_notified, discord_notified_at FROM contests"
                ).fetchall()
            }
            connection.execute("BEGIN")
            connection.execute("DELETE FROM contests")
            connection.executemany(
                """
                INSERT INTO contests (
                    contest_key,
                    source,
                    source_label,
                    source_id,
                    title,
                    normalized_title,
                    status,
                    detail_url,
                    organizer,
                    start_at,
                    finish_at,
                    format,
                    weight,
                    participants,
                    onsite,
                    location,
                    image_url,
                    registration_period,
                    contest_period,
                    finals_period,
                    mode,
                    scraped_at,
                    discord_notified,
                    discord_notified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        contest.contest_key,
                        contest.source,
                        contest.source_label,
                        contest.source_id,
                        contest.title,
                        contest.normalized_title,
                        contest.status,
                        contest.detail_url,
                        contest.organizer,
                        contest.start.isoformat() if contest.start else None,
                        contest.finish.isoformat() if contest.finish else None,
                        contest.format,
                        contest.weight,
                        contest.participants,
                        1 if contest.onsite else 0 if contest.onsite is not None else None,
                        contest.location,
                        contest.image_url,
                        contest.registration_period,
                        contest.contest_period,
                        contest.finals_period,
                        contest.mode,
                        contest.scraped_at.isoformat(),
                        1
                        if existing_notification_state.get(contest.contest_key, (contest.discord_notified, contest.discord_notified_at))[0]
                        else 0,
                        (
                            existing_notification_state.get(contest.contest_key, (contest.discord_notified, contest.discord_notified_at))[1]
                            or contest.discord_notified_at
                        ).isoformat()
                        if (
                            existing_notification_state.get(contest.contest_key, (contest.discord_notified, contest.discord_notified_at))[1]
                            or contest.discord_notified_at
                        )
                        else None,
                    )
                    for contest in contests
                ],
            )
            metadata = {
                "last_refreshed_at": refreshed_at.isoformat(),
            }
            for key, value in metadata.items():
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
                )
            count = connection.execute("SELECT COUNT(*) FROM contests").fetchone()[0]
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("record_count", str(count)),
            )
            connection.commit()

    def list_unnotified_contests(self, limit: int | None = None) -> list[StoredContest]:
        if not self.db_path.exists():
            raise StorageError(f"CTF DB not found: {self.db_path}")

        self.delete_finished_contests()

        query = [
            """
            SELECT
                contest_key,
                source,
                source_label,
                source_id,
                title,
                normalized_title,
                status,
                detail_url,
                organizer,
                start_at,
                finish_at,
                format,
                weight,
                participants,
                onsite,
                location,
                image_url,
                registration_period,
                contest_period,
                finals_period,
                mode,
                scraped_at,
                discord_notified,
                discord_notified_at
            FROM contests
            WHERE discord_notified = 0
            ORDER BY CASE WHEN status = 'ongoing' THEN 0 ELSE 1 END,
                     CASE WHEN start_at IS NULL THEN 1 ELSE 0 END,
                     start_at,
                     title
            """
        ]
        params: list[object] = []
        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute("\n".join(query), params).fetchall()
        return [self._row_to_stored_contest(row) for row in rows]

    def mark_contests_notified(self, contest_keys: Iterable[str], notified_at: datetime | None = None) -> int:
        keys = list(dict.fromkeys(contest_keys))
        if not keys or not self.db_path.exists():
            return 0

        mark_time = (notified_at or datetime.now(timezone.utc)).isoformat()
        placeholders = ", ".join("?" for _ in keys)
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            cursor = connection.execute(
                f"""
                UPDATE contests
                SET discord_notified = 1,
                    discord_notified_at = ?
                WHERE contest_key IN ({placeholders})
                """,
                [mark_time, *keys],
            )
            updated = cursor.rowcount if cursor.rowcount is not None else 0
            connection.commit()
        return updated

    def delete_finished_contests(self, reference_time: datetime | None = None) -> int:
        if not self.db_path.exists():
            return 0

        cutoff = (reference_time or datetime.now(timezone.utc)).isoformat()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN")
            cursor = connection.execute(
                "DELETE FROM contests WHERE finish_at IS NOT NULL AND finish_at <= ?",
                (cutoff,),
            )
            deleted = cursor.rowcount if cursor.rowcount is not None else 0
            if deleted:
                count = connection.execute("SELECT COUNT(*) FROM contests").fetchone()[0]
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    ("record_count", str(count)),
                )
            connection.commit()
        return deleted

    def list_contests(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        source: str | None = None,
        limit: int | None = None,
    ) -> list[StoredContest]:
        if not self.db_path.exists():
            raise StorageError(f"CTF DB not found: {self.db_path}")

        self.delete_finished_contests()

        query = [
            """
            SELECT
                contest_key,
                source,
                source_label,
                source_id,
                title,
                normalized_title,
                status,
                detail_url,
                organizer,
                start_at,
                finish_at,
                format,
                weight,
                participants,
                onsite,
                location,
                image_url,
                registration_period,
                contest_period,
                finals_period,
                mode,
                scraped_at,
                discord_notified,
                discord_notified_at
            FROM contests
            WHERE 1=1
            """
        ]
        params: list[object] = []

        if status:
            query.append("AND status = ?")
            params.append(status)
        if source:
            query.append("AND source = ?")
            params.append(source)
        if search:
            query.append("AND LOWER(title) LIKE ?")
            params.append(f"%{search.casefold()}%")

        if status == "ongoing":
            query.append("ORDER BY CASE WHEN finish_at IS NULL THEN 1 ELSE 0 END, finish_at, title")
        else:
            query.append("ORDER BY CASE WHEN start_at IS NULL THEN 1 ELSE 0 END, start_at, title")

        if limit is not None:
            query.append("LIMIT ?")
            params.append(limit)

        with closing(self._connect()) as connection:
            rows = connection.execute("\n".join(query), params).fetchall()
        return [self._row_to_stored_contest(row) for row in rows]

    def get_metadata(self) -> dict[str, str]:
        if not self.db_path.exists():
            raise StorageError(f"CTF DB not found: {self.db_path}")
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS contests (
                contest_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_label TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                status TEXT NOT NULL,
                detail_url TEXT NOT NULL,
                organizer TEXT,
                start_at TEXT,
                finish_at TEXT,
                format TEXT,
                weight REAL,
                participants INTEGER,
                onsite INTEGER,
                location TEXT,
                image_url TEXT,
                registration_period TEXT,
                contest_period TEXT,
                finals_period TEXT,
                mode TEXT,
                scraped_at TEXT NOT NULL,
                discord_notified INTEGER NOT NULL DEFAULT 0,
                discord_notified_at TEXT
            );

            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        existing_columns = {row["name"] for row in connection.execute("PRAGMA table_info(contests)").fetchall()}
        if "discord_notified" not in existing_columns:
            connection.execute("ALTER TABLE contests ADD COLUMN discord_notified INTEGER NOT NULL DEFAULT 0")
        if "discord_notified_at" not in existing_columns:
            connection.execute("ALTER TABLE contests ADD COLUMN discord_notified_at TEXT")
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_contests_status_start ON contests(status, start_at);
            CREATE INDEX IF NOT EXISTS idx_contests_source_status ON contests(source, status);
            CREATE INDEX IF NOT EXISTS idx_contests_title ON contests(title);
            CREATE INDEX IF NOT EXISTS idx_contests_notified_status ON contests(discord_notified, status, start_at);
            """
        )

    def _row_to_stored_contest(self, row: sqlite3.Row) -> StoredContest:
        return StoredContest(
            contest_key=row["contest_key"],
            source=row["source"],
            source_label=row["source_label"],
            source_id=row["source_id"],
            title=row["title"],
            normalized_title=row["normalized_title"],
            status=row["status"],
            detail_url=row["detail_url"],
            organizer=row["organizer"],
            start=datetime.fromisoformat(row["start_at"]) if row["start_at"] else None,
            finish=datetime.fromisoformat(row["finish_at"]) if row["finish_at"] else None,
            format=row["format"],
            weight=float(row["weight"]) if row["weight"] is not None else None,
            participants=int(row["participants"]) if row["participants"] is not None else None,
            onsite=bool(row["onsite"]) if row["onsite"] is not None else None,
            location=row["location"],
            image_url=row["image_url"],
            registration_period=row["registration_period"],
            contest_period=row["contest_period"],
            finals_period=row["finals_period"],
            mode=row["mode"],
            scraped_at=datetime.fromisoformat(row["scraped_at"]),
            discord_notified=bool(row["discord_notified"]) if "discord_notified" in row.keys() else False,
            discord_notified_at=(
                datetime.fromisoformat(row["discord_notified_at"])
                if "discord_notified_at" in row.keys() and row["discord_notified_at"]
                else None
            ),
        )
