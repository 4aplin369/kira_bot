# -*- coding: utf-8 -*-
"""Слой хранения данных (SQLite). Версия 2.

Лёгкая обёртка над stdlib-модулем sqlite3: одна база, инициализация схемы
при старте, функции-помощники по таблицам. Запросы маленькие и редкие
(пара на действие пользователя), поэтому синхронного sqlite3 достаточно —
блокировка событийного цикла пренебрежимо мала.

Путь к базе берётся из переменной окружения DB_PATH.
На Amvera задать DB_PATH=/data/kira_bot.sqlite3 (постоянный диск /data),
локально по умолчанию кладём рядом в папку data/.
"""

import os
import sqlite3
import logging
from contextlib import closing

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "kira_bot.sqlite3"))


def _connect() -> sqlite3.Connection:
    """Новое соединение. Оборачивать в `with closing(...)`, чтобы оно закрылось,
    и во вложенный `with conn:` — для фиксации транзакции."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Создаёт файл базы и таблицы, если их ещё нет. Зовётся один раз при старте."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with closing(_connect()) as conn, conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                tg_id      INTEGER PRIMARY KEY,
                name       TEXT,
                role       TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Дневник: фото животика по неделям. Привязка к user_id —
            -- у каждого свой дневник, фото не пересекаются.
            CREATE TABLE IF NOT EXISTS diary (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       INTEGER NOT NULL,
                week          INTEGER,
                photo_file_id TEXT NOT NULL,   -- file_id фото в Telegram
                note          TEXT,            -- подпись к фото, если была
                created_at    TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_diary_user ON diary(user_id);

            -- Счётчик шевелений: по одному значению на пользователя.
            -- Хранится в БД, поэтому переживает перезапуск бота.
            CREATE TABLE IF NOT EXISTS moves (
                user_id    INTEGER PRIMARY KEY,
                count      INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            """
        )
    logging.info("База данных готова: %s", DB_PATH)


def upsert_user(tg_id: int, name: str, role: str) -> None:
    """Создаёт пользователя или обновляет имя/роль. Дату родов не трогает."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO users (tg_id, name, role) VALUES (?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                name = excluded.name,
                role = excluded.role
            """,
            (tg_id, name, role),
        )


def get_all_user_ids() -> list[int]:
    """Все, кто хоть раз заходил в бота (нажимал /start) — для рассылки-анонса."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT tg_id FROM users").fetchall()
    return [r["tg_id"] for r in rows]


# ─────────────────────────────────────────────────────────────────────
# Дневник (фото животика)
# ─────────────────────────────────────────────────────────────────────
def add_photo(user_id: int, week: int | None, photo_file_id: str, note: str | None) -> None:
    """Сохраняет фото в дневник пользователя."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT INTO diary (user_id, week, photo_file_id, note) VALUES (?, ?, ?, ?)",
            (user_id, week, photo_file_id, note),
        )


def count_photos(user_id: int) -> int:
    """Сколько фото в дневнике пользователя."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM diary WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["n"] if row else 0


def get_photos(user_id: int) -> list[sqlite3.Row]:
    """Все фото пользователя по порядку: по неделе, затем по времени добавления."""
    with closing(_connect()) as conn:
        return conn.execute(
            """
            SELECT week, photo_file_id, note
            FROM diary
            WHERE user_id = ?
            ORDER BY week IS NULL, week, created_at, id
            """,
            (user_id,),
        ).fetchall()


# ─────────────────────────────────────────────────────────────────────
# Счётчик шевелений (хранится в БД — переживает перезапуск)
# ─────────────────────────────────────────────────────────────────────
def get_moves(user_id: int) -> int:
    """Текущее число шевелений пользователя (0, если ещё не считал)."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT count FROM moves WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["count"] if row else 0


def add_move(user_id: int) -> int:
    """Увеличивает счётчик на 1 и возвращает новое значение."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO moves (user_id, count) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET
                count = count + 1,
                updated_at = datetime('now')
            """,
            (user_id,),
        )
        row = conn.execute(
            "SELECT count FROM moves WHERE user_id = ?", (user_id,)
        ).fetchone()
    return row["count"]


def reset_moves(user_id: int) -> None:
    """Сбрасывает счётчик в 0."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO moves (user_id, count) VALUES (?, 0)
            ON CONFLICT(user_id) DO UPDATE SET
                count = 0,
                updated_at = datetime('now')
            """,
            (user_id,),
        )
