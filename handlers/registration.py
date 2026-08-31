"""Регистрация: номер телефона -> ФИО -> выдача ID аккаунта."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardRemove

import keyboards as kb
from config import ADMIN_IDS
from db import (
    add_transaction,
    create_user,
    format_phone,
    get_settings,
    get_user_by_tg,
)

router = Router()


class Reg(StatesGroup):
    phone = State()
    full_name = State()


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


async def show_main_menu(message: Message, user: dict) -> None:
    s = await get_settings()
    await message.answer(
        f"👤 ID аккаунта: <code>{user['account_code']}</code>\n"
        f"💰 Баланс: <b>{user['points']}</b> баллов\n"
        f"1 балл = {s['point_rate']} ₽",
        reply_markup=kb.client_menu(is_admin(message.from_user.id)),
    )


@router.message(Command("myid"))
async def cmd_myid(message: Message) -> None:
    await message.answer(
        f"Твой Telegram ID: <code>{message.from_user.id}</code>\n"
        "Передай это число тому, кто настраивает бота, чтобы получить права администратора."
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await get_user_by_tg(message.from_user.id)
    if user:
        await message.answer("С возвращением! 👋")
        await show_main_menu(message, user)
        return
    await message.answer(
        "Привет! Это бот программы лояльности.\n\n"
        "Для регистрации введите ваш номер телефона.\n"
        "Например: <i>+7 900 123-45-67</i>",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(Reg.phone)


async def _ask_full_name(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Отлично! Теперь напишите свои ФИО одной строкой.\n"
        "Например: <i>Иванов Иван Иванович</i>"
    )
    await state.set_state(Reg.full_name)


@router.message(Reg.phone, F.contact)
async def reg_contact(message: Message, state: FSMContext) -> None:
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer("Отправьте, пожалуйста, свой собственный номер.")
        return
    await state.update_data(phone=message.contact.phone_number)
    await _ask_full_name(message, state)


@router.message(Reg.phone, F.text)
async def reg_phone_text(message: Message, state: FSMContext) -> None:
    digits = "".join(ch for ch in message.text if ch.isdigit())
    if not 10 <= len(digits) <= 15:
        await message.answer(
            "Не похоже на номер телефона. Введите ещё раз, например: +7 900 123-45-67"
        )
        return
    await state.update_data(phone=digits)
    await _ask_full_name(message, state)


@router.message(Reg.full_name, F.text)
async def reg_full_name(message: Message, state: FSMContext) -> None:
    full_name = " ".join(message.text.split())
    if len(full_name) < 3:
        await message.answer("Слишком коротко. Напиши ФИО полностью.")
        return
    data = await state.get_data()
    user = await create_user(message.from_user.id, data["phone"], full_name)

    s = await get_settings()
    bonus = int(s.get("signup_bonus", "0") or "0")
    if bonus > 0:
        await add_transaction(
            user["id"], "accrual", bonus, comment="приветственный бонус за регистрацию"
        )
        user = await get_user_by_tg(message.from_user.id)

    await state.clear()
    text = (
        "Регистрация завершена! 🎉\n"
        f"Твой индивидуальный ID аккаунта: <code>{user['account_code']}</code>\n"
    )
    if bonus > 0:
        text += f"🎁 Начислен приветственный бонус: <b>{bonus}</b> баллов!\n"
    text += "Назови ID на кассе, чтобы копить и тратить баллы."
    await message.answer(text)

    await show_main_menu(message, user)
    await _notify_admins_new_client(message, user, bonus)


async def _notify_admins_new_client(message: Message, user: dict, bonus: int = 0) -> None:
    uname = f"@{message.from_user.username}" if message.from_user.username else "—"
    text = (
        "🆕 <b>Новый клиент зарегистрирован</b>\n"
        f"ФИО: {user['full_name']}\n"
        f"ID аккаунта: <code>{user['account_code']}</code>\n"
        f"Телефон: {format_phone(user['phone'])}\n"
        f"Telegram: {uname} (id {message.from_user.id})\n"
        f"Дата: {user['created_at'][:16].replace('T', ' ')}"
    )
    if bonus > 0:
        text += f"\nПриветственный бонус: +{bonus} баллов (баланс {user['points']})"
    for admin_id in ADMIN_IDS:
        if admin_id == message.from_user.id:
            continue
        try:
            await message.bot.send_message(admin_id, text)
        except Exception:
            pass
