import sqlite3
from datetime import datetime

DB_PATH = "thoughts.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS thoughts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id   INTEGER NOT NULL,
                text      TEXT    NOT NULL,
                timestamp TEXT    NOT NULL
            )
        """)


def add_thought(user_id: int, text: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO thoughts (user_id, text, timestamp) VALUES (?, ?, ?)",
            (user_id, text, datetime.utcnow().isoformat()),
        )


def get_and_clear_thoughts(user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT text FROM thoughts WHERE user_id = ? ORDER BY timestamp",
            (user_id,),
        ).fetchall()
        conn.execute("DELETE FROM thoughts WHERE user_id = ?", (user_id,))
    return "\n---\n".join(row[0] for row in rows)
