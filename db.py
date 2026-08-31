"""Слой доступа к базе данных (SQLite через aiosqlite)."""

import os
import secrets
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config import ACCOUNT_CODE_LENGTH, ACCOUNT_CODE_PREFIX, DB_PATH, DEFAULT_SETTINGS

# Алфавит для кода аккаунта — без похожих символов (0/O, 1/I/L).
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _random_code() -> str:
    body = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(ACCOUNT_CODE_LENGTH))
    return f"{ACCOUNT_CODE_PREFIX}{body}"


def normalize_phone(raw: str) -> str:
    """Оставляем только цифры и берём последние 10 (для сопоставления номеров)."""
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


def format_phone(phone: str) -> str:
    """10 цифр -> +7 (914) 951-40-47."""
    p = (phone or "").strip()
    if len(p) == 10 and p.isdigit():
        return f"+7 ({p[:3]}) {p[3:6]}-{p[6:8]}-{p[8:]}"
    return p or "—"


async def _unique_account_code(db: aiosqlite.Connection) -> str:
    while True:
        code = _random_code()
        async with db.execute(
            "SELECT 1 FROM users WHERE account_code = ?", (code,)
        ) as cur:
            if await cur.fetchone() is None:
                return code


async def init_db() -> None:
    # создаём каталог для базы, если задан путь вида /app/data/loyalty.db
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tg_id        INTEGER UNIQUE NOT NULL,
                account_code TEXT UNIQUE,
                phone        TEXT,
                full_name    TEXT,
                points       INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                type       TEXT NOT NULL,           -- 'accrual' | 'redeem'
                points     INTEGER NOT NULL,        -- + начисление, - списание
                money      REAL,                    -- сумма оплаты (для начислений)
                comment    TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS redeem_requests (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                points         INTEGER NOT NULL,   -- сколько баллов просил клиент
                approved_points INTEGER,           -- сколько реально списано
                purchase_total REAL,               -- сумма покупки, ₽
                status         TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
                created_at     TEXT NOT NULL,
                processed_at   TEXT
            );
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # --- миграция со старой схемы (числовой id как код аккаунта) ---
        async with db.execute("PRAGMA table_info(users)") as cur:
            columns = [row[1] for row in await cur.fetchall()]
        if "account_code" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN account_code TEXT")
        async with db.execute(
            "SELECT id FROM users WHERE account_code IS NULL OR account_code = ''"
        ) as cur:
            missing = [row[0] for row in await cur.fetchall()]
        for uid in missing:
            await db.execute(
                "UPDATE users SET account_code = ? WHERE id = ?",
                (await _unique_account_code(db), uid),
            )
        # если в префиксе нет дефиса — убираем дефисы и из уже выданных кодов
        if "-" not in ACCOUNT_CODE_PREFIX:
            await db.execute(
                "UPDATE users SET account_code = REPLACE(account_code, '-', '') "
                "WHERE account_code LIKE '%-%'"
            )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_account_code "
            "ON users(account_code)"
        )

        # миграция redeem_requests: новые колонки
        async with db.execute("PRAGMA table_info(redeem_requests)") as cur:
            rr_cols = [row[1] for row in await cur.fetchall()]
        if "approved_points" not in rr_cols:
            await db.execute("ALTER TABLE redeem_requests ADD COLUMN approved_points INTEGER")
        if "purchase_total" not in rr_cols:
            await db.execute("ALTER TABLE redeem_requests ADD COLUMN purchase_total REAL")

        for key, value in DEFAULT_SETTINGS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
            )
        await db.commit()


# --------------------------- настройки ---------------------------


async def get_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM settings") as cur:
            rows = await cur.fetchall()
    data = {k: v for k, v in rows}
    for k, v in DEFAULT_SETTINGS.items():
        data.setdefault(k, v)
    return data


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*), COALESCE(SUM(points), 0) FROM users"
        ) as cur:
            users_count, points_total = await cur.fetchone()
        async with db.execute(
            "SELECT COUNT(*) FROM redeem_requests WHERE status = 'pending'"
        ) as cur:
            (pending,) = await cur.fetchone()
    return {
        "users_count": users_count,
        "points_total": points_total,
        "pending_requests": pending,
    }


async def set_setting(key: str, value: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await db.commit()


# --------------------------- пользователи ---------------------------


async def _fetch_one(query: str, params: tuple) -> Optional[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, params) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def get_user_by_tg(tg_id: int) -> Optional[dict]:
    return await _fetch_one("SELECT * FROM users WHERE tg_id = ?", (tg_id,))


async def get_user_by_id(user_id: int) -> Optional[dict]:
    return await _fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))


async def get_user_by_code(code: str) -> Optional[dict]:
    norm = code.strip().upper().replace(" ", "")
    user = await _fetch_one("SELECT * FROM users WHERE account_code = ?", (norm,))
    if not user and "-" in norm:  # запасной вариант для старого формата с дефисом
        user = await _fetch_one(
            "SELECT * FROM users WHERE account_code = ?", (norm.replace("-", ""),)
        )
    return user


async def get_user_by_phone(phone: str) -> Optional[dict]:
    return await _fetch_one(
        "SELECT * FROM users WHERE phone = ?", (normalize_phone(phone),)
    )


async def get_users_by_name(query: str, limit: int = 10) -> list:
    """Поиск по подстроке ФИО (регистронезависимо, в т.ч. кириллица)."""
    q = query.strip().lower()
    if not q:
        return []
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY full_name") as cur:
            rows = await cur.fetchall()
    matched = [
        dict(r) for r in rows if r["full_name"] and q in r["full_name"].lower()
    ]
    return matched[:limit]


async def create_user(tg_id: int, phone: str, full_name: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        code = await _unique_account_code(db)
        await db.execute(
            "INSERT INTO users(tg_id, account_code, phone, full_name, points, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (tg_id, code, normalize_phone(phone), full_name, _now()),
        )
        await db.commit()
    return await get_user_by_tg(tg_id)


async def add_transaction(
    user_id: int,
    type_: str,
    points: int,
    money: Optional[float] = None,
    comment: Optional[str] = None,
) -> None:
    """Меняет баланс пользователя и пишет запись в историю (одной транзакцией)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET points = points + ? WHERE id = ?", (points, user_id)
        )
        await db.execute(
            "INSERT INTO transactions(user_id, type, points, money, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, type_, points, money, comment, _now()),
        )
        await db.commit()


async def get_history(user_id: int, limit: int = 10) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


# --------------------------- заявки на списание ---------------------------


async def create_redeem_request(user_id: int, points: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO redeem_requests(user_id, points, status, created_at) "
            "VALUES (?, ?, 'pending', ?)",
            (user_id, points, _now()),
        )
        await db.commit()
        return cur.lastrowid


async def get_request(request_id: int) -> Optional[dict]:
    return await _fetch_one(
        "SELECT * FROM redeem_requests WHERE id = ?", (request_id,)
    )


async def get_pending_requests() -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM redeem_requests WHERE status = 'pending' ORDER BY id"
        ) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def resolve_request(
    request_id: int,
    status: str,
    approved_points: Optional[int] = None,
    purchase_total: Optional[float] = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE redeem_requests "
            "SET status = ?, approved_points = ?, purchase_total = ?, processed_at = ? "
            "WHERE id = ?",
            (status, approved_points, purchase_total, _now(), request_id),
        )
        await db.commit()
