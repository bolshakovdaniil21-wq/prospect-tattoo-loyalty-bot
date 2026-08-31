"""Админ-панель: начисление, списание при оплате, баллы клиента, заявки, настройки."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import keyboards as kb
from config import ADMIN_IDS
from db import (
    add_transaction,
    format_phone,
    get_pending_requests,
    get_request,
    get_settings,
    get_stats,
    get_user_by_code,
    get_user_by_id,
    get_user_by_phone,
    get_users_by_name,
    normalize_phone,
    resolve_request,
    set_setting,
)

router = Router()

# Весь роутер работает только для админов.
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))

SETTING_LABELS = {
    "accrual_percent": "процент начисления, %",
    "point_rate": "курс балла, ₽ за 1 балл",
    "min_redeem": "минимум баллов для списания",
    "max_redeem_share": "макс. доля оплаты баллами, % от чека",
    "signup_bonus": "бонус за регистрацию, баллов",
}
INT_SETTINGS = ("accrual_percent", "min_redeem", "max_redeem_share", "signup_bonus")


class Accrue(StatesGroup):
    client = State()
    amount = State()


class AdminRedeem(StatesGroup):
    client = State()
    total = State()
    points = State()


class ClientInfo(StatesGroup):
    query = State()


class ApproveRedeem(StatesGroup):
    purchase_total = State()


class EditSetting(StatesGroup):
    value = State()


def _client_card(u: dict) -> str:
    return (
        f"👤 {u['full_name']}\n"
        f"ID: <code>{u['account_code']}</code>\n"
        f"Телефон: {format_phone(u['phone'])}\n"
        f"Баланс: <b>{u['points']}</b> баллов"
    )


async def _resolve_client(message: Message, text: str, action: str):
    """Ищет клиента по телефону / ID / ФИО.

    Возвращает dict, либо None (тогда клиенту уже отправлено сообщение —
    'не найдено' или список для выбора).
    """
    user = None
    if len(normalize_phone(text)) >= 4:
        user = await get_user_by_phone(text)
    if not user:
        user = await get_user_by_code(text)
    if user:
        return user

    matches = await get_users_by_name(text)
    if not matches:
        await message.answer(
            "Клиент не найден. Введи телефон, ФИО или ID ещё раз (или /admin — отмена)."
        )
        return None
    if len(matches) == 1:
        return matches[0]
    await message.answer(
        "Найдено несколько клиентов — выбери:",
        reply_markup=kb.pick_client_kb(matches, action),
    )
    return None


# --------------------------- вход / выход ---------------------------


@router.message(Command("admin"))
@router.message(F.text == kb.BTN_ADMIN_ENTER)
async def admin_enter(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🛠 Админ-панель", reply_markup=kb.admin_menu())


@router.message(F.text == kb.BTN_ADMIN_EXIT)
async def admin_exit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Вышел из админки.", reply_markup=kb.client_menu(is_admin=True))


# --------------------------- баллы клиента ---------------------------


@router.message(F.text == kb.BTN_ADMIN_BALANCE)
async def info_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ClientInfo.query)
    await message.answer("Введи телефон, ФИО или ID клиента:")


@router.message(ClientInfo.query, F.text)
async def info_query(message: Message, state: FSMContext) -> None:
    user = await _resolve_client(message, message.text, "info")
    if user:
        await state.clear()
        await message.answer(_client_card(user), reply_markup=kb.admin_menu())


# --------------------------- начисление баллов ---------------------------


@router.message(F.text == kb.BTN_ADMIN_ACCRUE)
async def accrue_start(message: Message, state: FSMContext) -> None:
    await state.set_state(Accrue.client)
    await message.answer("Начисление баллов.\nВведи телефон, ФИО или ID клиента:")


@router.message(Accrue.client, F.text)
async def accrue_client(message: Message, state: FSMContext) -> None:
    user = await _resolve_client(message, message.text, "accrue")
    if user:
        await _ask_accrue_amount(message, user, state)


async def _ask_accrue_amount(target: Message, user: dict, state: FSMContext) -> None:
    await state.set_state(Accrue.amount)
    await state.update_data(user_id=user["id"])
    await target.answer(
        f"Клиент: {user['full_name']} (ID {user['account_code']}), "
        f"баланс {user['points']} баллов.\n"
        "Введи сумму оплаты в рублях:"
    )


@router.message(Accrue.amount, F.text)
async def accrue_amount(message: Message, state: FSMContext) -> None:
    try:
        money = float(message.text.strip().replace(",", "."))
        if money <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи положительное число.")
        return

    data = await state.get_data()
    user = await get_user_by_id(data["user_id"])
    if not user:
        await state.clear()
        await message.answer("Клиент не найден.", reply_markup=kb.admin_menu())
        return

    s = await get_settings()
    percent = float(s["accrual_percent"])
    points = round(money * percent / 100)

    await add_transaction(
        user["id"], "accrual", points,
        money=money, comment=f"оплата {money:.2f} ₽, {percent}%",
    )
    await state.clear()
    new_balance = user["points"] + points
    await message.answer(
        f"✅ Начислено <b>{points}</b> баллов клиенту {user['full_name']} "
        f"(ID {user['account_code']}).\nНовый баланс: <b>{new_balance}</b>.",
        reply_markup=kb.admin_menu(),
    )
    await _notify(
        message.bot, user["tg_id"],
        f"🎉 Вам начислено <b>{points}</b> баллов за оплату {money:.0f} ₽.\n"
        f"Баланс: <b>{new_balance}</b>.",
    )


# --------------------------- списание при оплате (админ) ---------------------------


@router.message(F.text == kb.BTN_ADMIN_REDEEM)
async def redeem_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AdminRedeem.client)
    await message.answer("Списание баллов при оплате.\nВведи телефон, ФИО или ID клиента:")


@router.message(AdminRedeem.client, F.text)
async def redeem_client(message: Message, state: FSMContext) -> None:
    user = await _resolve_client(message, message.text, "redeem")
    if user:
        await _ask_redeem_total(message, user, state)


async def _ask_redeem_total(target: Message, user: dict, state: FSMContext) -> None:
    if user["points"] <= 0:
        await state.clear()
        await target.answer(
            f"У клиента {user['full_name']} нет баллов.", reply_markup=kb.admin_menu()
        )
        return
    await state.set_state(AdminRedeem.total)
    await state.update_data(user_id=user["id"])
    await target.answer(
        f"Клиент: {user['full_name']} (ID {user['account_code']}), "
        f"баланс {user['points']} баллов.\n"
        "Введи сумму покупки в рублях:"
    )


@router.message(AdminRedeem.total, F.text)
async def redeem_total(message: Message, state: FSMContext) -> None:
    try:
        total = float(message.text.strip().replace(",", "."))
        if total <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи положительное число — сумму покупки в ₽.")
        return

    data = await state.get_data()
    user = await get_user_by_id(data["user_id"])
    s = await get_settings()
    rate = float(s["point_rate"])
    share = float(s["max_redeem_share"])

    max_by_share = int(total * share / 100 / rate) if rate > 0 else 0
    max_allowed = min(user["points"], max_by_share)
    if max_allowed <= 0:
        await state.clear()
        await message.answer(
            f"Баллами оплатить нельзя: лимит {share:.0f}% от {total:.0f} ₽, "
            f"баланс клиента {user['points']}.",
            reply_markup=kb.admin_menu(),
        )
        return

    await state.update_data(total=total, max_allowed=max_allowed)
    await state.set_state(AdminRedeem.points)
    await message.answer(
        f"Покупка {total:.0f} ₽. Можно списать до <b>{max_allowed}</b> баллов.\n"
        "Сколько списываем?"
    )


@router.message(AdminRedeem.points, F.text)
async def redeem_points(message: Message, state: FSMContext) -> None:
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("Введи число.")
        return
    points = int(raw)
    data = await state.get_data()

    if points == 0:
        await state.clear()
        await message.answer("Отменено.", reply_markup=kb.admin_menu())
        return
    if points > data["max_allowed"]:
        await message.answer(f"Не больше {data['max_allowed']}. Введи ещё раз.")
        return

    user = await get_user_by_id(data["user_id"])
    if not user or points > user["points"]:
        await state.clear()
        await message.answer("Недостаточно баллов у клиента.", reply_markup=kb.admin_menu())
        return

    total = data["total"]
    await add_transaction(
        user["id"], "redeem", -points,
        money=total, comment=f"списание при оплате, покупка {total:.2f} ₽",
    )
    await state.clear()

    rate = float((await get_settings())["point_rate"])
    paid = points * rate
    to_pay = total - paid
    await message.answer(
        f"✅ Списано <b>{points}</b> баллов (−{paid:.0f} ₽).\n"
        f"Покупка {total:.0f} ₽ → доплата клиента: <b>{to_pay:.0f} ₽</b>.\n"
        f"Остаток баллов: {user['points'] - points}.",
        reply_markup=kb.admin_menu(),
    )
    await _notify(
        message.bot, user["tg_id"],
        f"💳 С вашего счёта списано <b>{points}</b> баллов за покупку на {total:.0f} ₽ "
        f"(−{paid:.0f} ₽).\nБаланс: <b>{user['points'] - points}</b>.",
    )


# --------------------------- выбор клиента из списка ---------------------------


@router.callback_query(F.data.startswith("pick:"))
async def pick_client(call: CallbackQuery, state: FSMContext) -> None:
    _, action, uid = call.data.split(":")
    user = await get_user_by_id(int(uid))
    try:
        await call.message.edit_reply_markup()
    except Exception:
        pass
    if not user:
        await call.answer("Клиент не найден.", show_alert=True)
        return
    if action == "accrue":
        await _ask_accrue_amount(call.message, user, state)
    elif action == "redeem":
        await _ask_redeem_total(call.message, user, state)
    else:
        await state.clear()
        await call.message.answer(_client_card(user), reply_markup=kb.admin_menu())
    await call.answer()


# --------------------------- заявки клиентов на списание ---------------------------


@router.message(F.text == kb.BTN_ADMIN_REQUESTS)
async def list_requests(message: Message) -> None:
    rows = await get_pending_requests()
    if not rows:
        await message.answer("Заявок на списание нет.")
        return
    for r in rows:
        user = await get_user_by_id(r["user_id"])
        await message.answer(
            f"<b>Заявка #{r['id']}</b>\n"
            f"Клиент: {user['full_name']} "
            f"(ID {user['account_code']}, тел. {format_phone(user['phone'])})\n"
            f"Хочет списать: {r['points']} баллов (баланс {user['points']})",
            reply_markup=kb.request_action_kb(r["id"]),
        )


@router.callback_query(F.data.startswith("req:"))
async def process_request(call: CallbackQuery, state: FSMContext) -> None:
    _, action, rid = call.data.split(":")
    req = await get_request(int(rid))
    base_text = call.message.text or f"Заявка #{rid}"

    if not req or req["status"] != "pending":
        await call.answer("Заявка уже обработана.", show_alert=True)
        try:
            await call.message.edit_reply_markup()
        except Exception:
            pass
        return

    if action == "reject":
        user = await get_user_by_id(req["user_id"])
        await resolve_request(req["id"], "rejected")
        await call.message.edit_text(base_text + "\n\n❌ Отклонено.")
        await _notify(
            call.bot, user["tg_id"],
            f"❌ Заявка на списание {req['points']} баллов отклонена.",
        )
        await call.answer()
        return

    # approve: спрашиваем сумму покупки (нужна для лимита "не более N% чека")
    await state.clear()
    await state.set_state(ApproveRedeem.purchase_total)
    await state.update_data(
        request_id=req["id"],
        msg_chat=call.message.chat.id,
        msg_id=call.message.message_id,
        base_text=base_text,
    )
    await call.message.answer(
        f"Заявка #{req['id']}: клиент хочет списать {req['points']} баллов.\n"
        "Введи полную сумму покупки в рублях:"
    )
    await call.answer()


@router.message(ApproveRedeem.purchase_total, F.text)
async def approve_redeem(message: Message, state: FSMContext) -> None:
    try:
        total = float(message.text.strip().replace(",", "."))
        if total <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи положительное число — сумму покупки в ₽.")
        return

    data = await state.get_data()
    await state.clear()
    req = await get_request(data["request_id"])
    if not req or req["status"] != "pending":
        await message.answer("Заявка уже обработана.", reply_markup=kb.admin_menu())
        return

    user = await get_user_by_id(req["user_id"])
    s = await get_settings()
    rate = float(s["point_rate"])
    share = float(s["max_redeem_share"])

    max_by_share = int(total * share / 100 / rate) if rate > 0 else 0
    allowed = min(req["points"], user["points"], max_by_share)

    if allowed <= 0:
        await message.answer(
            f"По сумме покупки {total:.0f} ₽ баллами оплатить нельзя "
            f"(лимит {share:.0f}% чека, у клиента {user['points']} баллов).\n"
            "Заявка осталась в списке.",
            reply_markup=kb.admin_menu(),
        )
        return

    await add_transaction(
        user["id"], "redeem", -allowed,
        money=total, comment=f"списание по заявке #{req['id']}, покупка {total:.2f} ₽",
    )
    await resolve_request(req["id"], "approved", approved_points=allowed, purchase_total=total)

    try:
        await message.bot.edit_message_text(
            data["base_text"] + f"\n\n✅ Списано {allowed} баллов (покупка {total:.0f} ₽).",
            chat_id=data["msg_chat"],
            message_id=data["msg_id"],
        )
    except Exception:
        pass

    paid = allowed * rate
    to_pay = total - paid
    note = "" if allowed == req["points"] else f"\n(клиент просил {req['points']})"
    await message.answer(
        f"✅ Списано <b>{allowed}</b> баллов (−{paid:.0f} ₽).{note}\n"
        f"Покупка {total:.0f} ₽ → доплата клиента: <b>{to_pay:.0f} ₽</b>.\n"
        f"Остаток баллов у клиента: {user['points'] - allowed}.",
        reply_markup=kb.admin_menu(),
    )
    await _notify(
        message.bot, user["tg_id"],
        f"✅ Списано <b>{allowed}</b> баллов за покупку на {total:.0f} ₽ "
        f"(−{paid:.0f} ₽).\nБаланс: <b>{user['points'] - allowed}</b>.",
    )


async def _notify(bot, chat_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id, text)
    except Exception:
        pass


# --------------------------- настройки ---------------------------


@router.message(F.text == kb.BTN_ADMIN_SETTINGS)
async def settings_view(message: Message) -> None:
    s = await get_settings()
    st = await get_stats()
    await message.answer(
        "<b>Статистика</b>\n"
        f"• зарегистрировано клиентов: <b>{st['users_count']}</b>\n"
        f"• баллов на счетах всего: {st['points_total']}\n"
        f"• заявок на списание в очереди: {st['pending_requests']}\n\n"
        "<b>Настройки лояльности</b>\n"
        f"• % начисления: {s['accrual_percent']}\n"
        f"• курс балла: {s['point_rate']} ₽ за 1 балл\n"
        f"• минимум для списания: {s['min_redeem']}\n"
        f"• баллами не более {s['max_redeem_share']}% от чека\n"
        f"• бонус за регистрацию: {s['signup_bonus']}",
        reply_markup=kb.settings_kb(),
    )


@router.callback_query(F.data.startswith("set:"))
async def settings_edit(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data.split(":")[1]
    await state.update_data(key=key)
    await state.set_state(EditSetting.value)
    await call.message.answer(f"Введи новое значение — {SETTING_LABELS[key]}:")
    await call.answer()


@router.message(EditSetting.value, F.text)
async def settings_save(message: Message, state: FSMContext) -> None:
    try:
        num = float(message.text.strip().replace(",", "."))
        if num < 0:
            raise ValueError
    except ValueError:
        await message.answer("Введи неотрицательное число.")
        return
    data = await state.get_data()
    key = data["key"]
    value = str(int(num)) if key in INT_SETTINGS else str(num)
    await set_setting(key, value)
    await state.clear()
    await message.answer(
        f"✅ Сохранено: {SETTING_LABELS[key]} = {value}",
        reply_markup=kb.admin_menu(),
    )
