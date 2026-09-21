"""Меню клиента: баланс, история, заявка на списание баллов."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import keyboards as kb
from config import ADMIN_IDS
from db import (
    create_redeem_request,
    format_birth_date,
    format_phone,
    get_history,
    get_settings,
    get_user_by_tg,
    parse_birth_date,
    set_birth_date,
)
from handlers.registration import show_main_menu

router = Router()


class Redeem(StatesGroup):
    amount = State()


class BirthEdit(StatesGroup):
    value = State()


async def _require_user(message: Message):
    user = await get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
    return user


async def _send_account(message: Message, user: dict) -> None:
    s = await get_settings()
    rub = user["points"] * float(s["point_rate"])
    await message.answer(
        "<b>Мой аккаунт</b>\n"
        f"🆔 ID: <code>{user['account_code']}</code>\n"
        f"👤 ФИО: {user['full_name']}\n"
        f"📱 Телефон: {format_phone(user['phone'])}\n"
        f"🎂 Дата рождения: {format_birth_date(user.get('birth_date'))}\n"
        f"📅 С нами с: {user['created_at'][:10]}\n\n"
        f"💰 Баланс: <b>{user['points']}</b> баллов (≈ {rub:.0f} ₽)\n"
        f"Курс: 1 балл = {s['point_rate']} ₽",
        reply_markup=kb.birth_edit_kb(bool(user.get("birth_date"))),
    )


@router.message(Command("balance"))
@router.message(F.text == kb.BTN_BALANCE)
async def balance(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await _require_user(message)
    if not user:
        return
    await _send_account(message, user)


@router.callback_query(F.data == "birth:edit")
async def birth_edit(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BirthEdit.value)
    await call.message.answer(
        "Введите дату рождения в формате <i>ДД.ММ.ГГГГ</i>, например 15.05.1990.",
        reply_markup=kb.birth_cancel_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "birth:cancel")
async def birth_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Хорошо, без изменений.")
    await call.answer()


@router.message(BirthEdit.value, F.text)
async def birth_save(message: Message, state: FSMContext) -> None:
    user = await get_user_by_tg(message.from_user.id)
    if not user:
        await state.clear()
        return
    birth = parse_birth_date(message.text)
    if not birth:
        await message.answer(
            "Не получилось распознать дату. Введите в формате <i>ДД.ММ.ГГГГ</i> "
            "(например 15.05.1990).",
            reply_markup=kb.birth_cancel_kb(),
        )
        return
    await set_birth_date(user["id"], birth)
    await state.clear()
    await message.answer("✅ Дата рождения сохранена.")
    await _send_account(message, await get_user_by_tg(message.from_user.id))


@router.message(F.text == kb.BTN_HISTORY)
async def history(message: Message) -> None:
    user = await _require_user(message)
    if not user:
        return
    rows = await get_history(user["id"])
    if not rows:
        await message.answer("Операций пока нет.")
        return
    labels = {"accrual": "начисление", "redeem": "списание"}
    lines = []
    for r in reversed(rows):  # от ранних к поздним, сверху вниз
        sign = "+" if r["points"] > 0 else ""
        lines.append(
            f"{r['created_at'][:10]}   {sign}{r['points']}   ({labels.get(r['type'], r['type'])})"
        )
    await message.answer("Последние операции:\n\n" + "\n".join(lines))


@router.message(Command("help"))
@router.message(F.text == kb.BTN_HELP)
async def help_handler(message: Message) -> None:
    s = await get_settings()
    await message.answer(
        "<b>Как работает программа лояльности</b>\n\n"
        f"• За каждую покупку начисляется <b>{s['accrual_percent']}%</b> баллами.\n"
        f"• 1 балл = {s['point_rate']} ₽.\n"
        f"• Баллами можно оплатить до <b>{s['max_redeem_share']}%</b> стоимости покупки.\n"
        f"• Списать можно от <b>{s['min_redeem']}</b> баллов.\n\n"
        "Чтобы потратить баллы: нажми «🎁 Списать баллы», укажи желаемое количество — "
        "заявка уйдёт администратору, он спишет баллы при оплате "
        "(в пределах лимита по сумме покупки)."
    )


@router.message(F.text == kb.BTN_REDEEM)
async def redeem_start(message: Message, state: FSMContext) -> None:
    user = await _require_user(message)
    if not user:
        return
    s = await get_settings()
    min_redeem = int(s["min_redeem"])
    if user["points"] < min_redeem:
        await message.answer(
            f"Недостаточно баллов. Минимум для списания — {min_redeem}, "
            f"у тебя сейчас {user['points']}."
        )
        return
    await message.answer(
        f"Сколько баллов списать? Введи число от {min_redeem} до {user['points']}."
    )
    await state.set_state(Redeem.amount)


@router.message(Redeem.amount, F.text)
async def redeem_amount(message: Message, state: FSMContext) -> None:
    user = await get_user_by_tg(message.from_user.id)
    if not user:
        await state.clear()
        return
    s = await get_settings()
    min_redeem = int(s["min_redeem"])
    raw = message.text.strip()
    if not raw.isdigit():
        await message.answer("Нужно ввести число.")
        return
    amount = int(raw)
    if amount < min_redeem or amount > user["points"]:
        await message.answer(f"Нужно число от {min_redeem} до {user['points']}.")
        return

    request_id = await create_redeem_request(user["id"], amount)
    await state.clear()
    s2 = await get_settings()
    await message.answer(
        f"✅ Заявка на списание <b>{amount}</b> баллов создана.\n"
        f"Спишется при оплате — но не более {s2['max_redeem_share']}% от суммы покупки."
    )
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(
                admin_id,
                f"🔔 <b>Заявка #{request_id}</b> на списание\n"
                f"Клиент: {user['full_name']} "
                f"(ID {user['account_code']}, тел. {format_phone(user['phone'])})\n"
                f"Списать: {amount} баллов (остаток станет {user['points'] - amount})",
                reply_markup=kb.request_action_kb(request_id),
            )
        except Exception:
            pass


@router.message(F.text)
async def fallback(message: Message) -> None:
    user = await get_user_by_tg(message.from_user.id)
    if not user:
        await message.answer("Нажми /start, чтобы зарегистрироваться.")
        return
    await show_main_menu(message, user)
