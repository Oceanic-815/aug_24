from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

_DB_FILENAME = "telezip.db"


@dataclass
class FileRecord:
    id: int
    original_path: str
    original_size: int
    added_at: datetime
    fragment_count: int
    fragment_names: List[str]
    message_ids: List[int]


class DatabaseManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.base_dir / _DB_FILENAME
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT NOT NULL,
                    original_size INTEGER NOT NULL,
                    added_at TEXT NOT NULL,
                    fragment_count INTEGER NOT NULL,
                    fragment_names TEXT NOT NULL,
                    message_ids TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def add_record(
        self,
        original_path: str,
        original_size: int,
        added_at: datetime,
        fragment_names: Iterable[str],
        message_ids: Iterable[int],
    ) -> int:
        fragment_names_list = list(fragment_names)
        message_ids_list = list(message_ids)
        fragment_names_json = json.dumps(fragment_names_list)
        message_ids_json = json.dumps(message_ids_list)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO files (
                    original_path, original_size, added_at,
                    fragment_count, fragment_names, message_ids
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    original_path,
                    original_size,
                    added_at.isoformat(),
                    len(fragment_names_list),
                    fragment_names_json,
                    message_ids_json,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def list_records(self) -> List[FileRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, original_path, original_size, added_at, fragment_count, fragment_names, message_ids FROM files ORDER BY added_at DESC"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def get_record(self, record_id: int) -> Optional[FileRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, original_path, original_size, added_at, fragment_count, fragment_names, message_ids FROM files WHERE id = ?",
                (record_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def update_message_ids(self, record_id: int, message_ids: Iterable[int]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE files SET message_ids = ? WHERE id = ?",
                (json.dumps(list(message_ids)), record_id),
            )
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> FileRecord:
        return FileRecord(
            id=row["id"],
            original_path=row["original_path"],
            original_size=row["original_size"],
            added_at=datetime.fromisoformat(row["added_at"]),
            fragment_count=row["fragment_count"],
            fragment_names=json.loads(row["fragment_names"]),
            message_ids=[int(mid) for mid in json.loads(row["message_ids"])],
        )

