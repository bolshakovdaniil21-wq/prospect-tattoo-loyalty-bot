from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# --- кнопки клиента ---
BTN_BALANCE = "💰 Мои баллы"
BTN_REDEEM = "🎁 Списать баллы"
BTN_HISTORY = "📜 История"
BTN_HELP = "ℹ️ Помощь"
BTN_ADMIN_ENTER = "🛠 Админ-панель"
BTN_SKIP = "⏭ Пропустить"

# --- кнопки админа ---
BTN_ADMIN_ACCRUE = "➕ Начислить баллы"
BTN_ADMIN_REDEEM = "💳 Списать баллы"
BTN_ADMIN_BALANCE = "🔍 Баллы клиента"
BTN_ADMIN_REQUESTS = "📥 Заявки на списание"
BTN_ADMIN_SETTINGS = "⚙️ Настройки"
BTN_ADMIN_EXIT = "⬅️ Выйти из админки"


def skip_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_SKIP)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def birth_edit_kb(has_date: bool) -> InlineKeyboardMarkup:
    text = "🎂 Изменить дату рождения" if has_date else "🎂 Указать дату рождения"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="birth:edit")]]
    )


def birth_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="birth:cancel")]]
    )


def client_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_REDEEM)],
        [KeyboardButton(text=BTN_HISTORY), KeyboardButton(text=BTN_HELP)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN_ENTER)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_ADMIN_ACCRUE), KeyboardButton(text=BTN_ADMIN_REDEEM)],
            [KeyboardButton(text=BTN_ADMIN_BALANCE), KeyboardButton(text=BTN_ADMIN_REQUESTS)],
            [KeyboardButton(text=BTN_ADMIN_SETTINGS)],
            [KeyboardButton(text=BTN_ADMIN_EXIT)],
        ],
        resize_keyboard=True,
    )


def request_action_kb(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить", callback_data=f"req:approve:{request_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить", callback_data=f"req:reject:{request_id}"
                ),
            ]
        ]
    )


def pick_client_kb(matches: list, action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{m['full_name']} · {m['account_code']}",
                    callback_data=f"pick:{action}:{m['id']}",
                )
            ]
            for m in matches
        ]
    )


def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить % начисления", callback_data="set:accrual_percent")],
            [InlineKeyboardButton(text="Изменить курс балла", callback_data="set:point_rate")],
            [InlineKeyboardButton(text="Изменить минимум списания", callback_data="set:min_redeem")],
            [InlineKeyboardButton(text="Изменить макс. % оплаты баллами", callback_data="set:max_redeem_share")],
            [InlineKeyboardButton(text="Изменить бонус за регистрацию", callback_data="set:signup_bonus")],
        ]
    )
