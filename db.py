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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emojis (
                emoji_char      TEXT PRIMARY KEY,
                custom_emoji_id TEXT NOT NULL
            )
        """)


def add_thought(user_id: int, text: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO thoughts (user_id, text, timestamp) VALUES (?, ?, ?)",
            (user_id, text, datetime.utcnow().isoformat()),
        )


def save_emoji(emoji_char: str, custom_emoji_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO emojis (emoji_char, custom_emoji_id) VALUES (?, ?)",
            (emoji_char, custom_emoji_id),
        )


def get_all_emojis() -> list[tuple[str, str]]:
    """Возвращает список (emoji_char, custom_emoji_id) из таблицы emojis."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT emoji_char, custom_emoji_id FROM emojis ORDER BY emoji_char"
        ).fetchall()


def get_and_clear_thoughts(user_id: int) -> str:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT text FROM thoughts WHERE user_id = ? ORDER BY timestamp",
            (user_id,),
        ).fetchall()
        conn.execute("DELETE FROM thoughts WHERE user_id = ?", (user_id,))
    return "\n---\n".join(row[0] for row in rows)
