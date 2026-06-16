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
from datetime import date

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
                due_date   TEXT,                       -- ISO ГГГГ-ММ-ДД, может быть NULL
                created_at TEXT DEFAULT (datetime('now'))
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


def get_due_date(tg_id: int) -> date | None:
    """Личная дата родов пользователя или None, если не задана."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT due_date FROM users WHERE tg_id = ?", (tg_id,)
        ).fetchone()
    if row and row["due_date"]:
        try:
            return date.fromisoformat(row["due_date"])
        except ValueError:
            return None
    return None


def set_due_date(tg_id: int, due: date) -> None:
    """Задаёт/меняет личную дату родов (создаёт строку пользователя при необходимости)."""
    with closing(_connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO users (tg_id, due_date) VALUES (?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET due_date = excluded.due_date
            """,
            (tg_id, due.isoformat()),
        )
