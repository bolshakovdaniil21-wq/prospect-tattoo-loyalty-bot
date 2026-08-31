import os

from dotenv import load_dotenv

load_dotenv()

# Токен бота из @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Владелец бота — единственный главный админ. Ему всегда доступна админ-панель.
_owner_raw = os.getenv("OWNER_ID", "").strip()
OWNER_ID = int(_owner_raw) if _owner_raw.isdigit() else None

# Доп. администраторы (сотрудники) через запятую — опционально.
# Для передачи бота владельцу оставь пустым: ADMIN_IDS=
_extra_admins = {
    int(x)
    for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",")
    if x.strip().isdigit()
}

# Итоговый список тех, у кого есть админ-панель.
ADMIN_IDS = set(_extra_admins)
if OWNER_ID:
    ADMIN_IDS.add(OWNER_ID)

# Файл базы данных SQLite
DB_PATH = os.getenv("DB_PATH", "loyalty.db")

# Индивидуальный код аккаунта клиента: префикс + случайные символы.
# Пример при префиксе "TT-" и длине 6: TT-A7K3QF
ACCOUNT_CODE_PREFIX = os.getenv("ACCOUNT_CODE_PREFIX", "")
ACCOUNT_CODE_LENGTH = int(os.getenv("ACCOUNT_CODE_LENGTH", "6"))

# Параметры лояльности по умолчанию.
# Их можно менять прямо из бота (Админ-панель → Настройки),
# значения сохраняются в базе.
DEFAULT_SETTINGS = {
    "accrual_percent": os.getenv("DEFAULT_ACCRUAL_PERCENT", "10"),   # % баллами от суммы покупки
    "point_rate": os.getenv("DEFAULT_POINT_RATE", "1"),              # сколько ₽ стоит 1 балл
    "min_redeem": os.getenv("DEFAULT_MIN_REDEEM", "1"),              # минимум баллов для списания
    "max_redeem_share": os.getenv("DEFAULT_MAX_REDEEM_SHARE", "50"), # баллами не более N% от чека
    "signup_bonus": os.getenv("DEFAULT_SIGNUP_BONUS", "1000"),       # бонус за регистрацию
}
