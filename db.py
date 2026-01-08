import sqlite3
from typing import Dict, Any

conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.executescript("""
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    threshold REAL DEFAULT 0.9,
    anon_reports INTEGER DEFAULT 1,
    logging INTEGER DEFAULT 1,
    max_warnings INTEGER DEFAULT 3,
    punishment TEXT DEFAULT 'ban'
);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    message_text TEXT,
    spam_prob REAL,
    reporter_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warnings (
    chat_id INTEGER,
    user_id INTEGER,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (chat_id, user_id)
);

CREATE TABLE IF NOT EXISTS banned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ml_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    message_text TEXT,
    spam_prob REAL,
    is_deleted INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")
conn.commit()


def ensure_chat(chat_id: int):
    cursor.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))
    conn.commit()


def get_chat_settings(chat_id: int) -> Dict[str, Any]:
    ensure_chat(chat_id)
    cursor.execute(
        "SELECT chat_id, threshold, anon_reports, logging, max_warnings, punishment FROM chats WHERE chat_id=?",
        (chat_id,)
    )
    row = cursor.fetchone()
    return {
        "chat_id": row[0],
        "threshold": row[1],
        "anon_reports": bool(row[2]),
        "logging": bool(row[3]),
        "max_warnings": row[4],
        "punishment": row[5]
    }


def set_chat_field(chat_id: int, field: str, value):
    cursor.execute(f"UPDATE chats SET {field}=? WHERE chat_id=?", (value, chat_id))
    conn.commit()
