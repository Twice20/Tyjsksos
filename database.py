import sqlite3
from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            files_received INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link TEXT UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_name TEXT,
            file_type TEXT DEFAULT 'document',
            caption TEXT
        )
    """)
    # На случай, если files уже существовала в старом виде (без этих колонок)
    cur.execute("PRAGMA table_info(files)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "file_type" not in existing_cols:
        cur.execute("ALTER TABLE files ADD COLUMN file_type TEXT DEFAULT 'document'")
    if "caption" not in existing_cols:
        cur.execute("ALTER TABLE files ADD COLUMN caption TEXT")
    conn.commit()
    conn.close()


# ---------- users ----------

def add_user(user_id: int, first_name: str, username: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO users (user_id, first_name, username) VALUES (?, ?, ?)",
        (user_id, first_name, username),
    )
    conn.commit()
    conn.close()


def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_users():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [r["user_id"] for r in rows]


def increment_files_received(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET files_received = files_received + 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()
    conn.close()


# ---------- channels (обязательная подписка) ----------

def add_channel(link: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO channels (link) VALUES (?)", (link,))
    conn.commit()
    conn.close()


def remove_channel(link: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE link = ?", (link,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0


def get_channels():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT link FROM channels")
    rows = cur.fetchall()
    conn.close()
    return [r["link"] for r in rows]


# ---------- files ----------

def add_file(file_id: str, file_name: str, file_type: str = "document", caption: str | None = None) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO files (file_id, file_name, file_type, caption) VALUES (?, ?, ?, ?)",
        (file_id, file_name, file_type, caption),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def get_file(file_db_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM files WHERE id = ?", (file_db_id,))
    row = cur.fetchone()
    conn.close()
    return row


def get_all_files():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, file_name, file_type FROM files ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows


def delete_file(file_db_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM files WHERE id = ?", (file_db_id,))
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed > 0
