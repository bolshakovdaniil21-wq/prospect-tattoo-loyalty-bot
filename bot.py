import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import BOT_TOKEN
from db import init_db
from handlers import admin, client, registration


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Регистрация / главное меню"),
            BotCommand(command="balance", description="Мои баллы"),
            BotCommand(command="help", description="Как это работает"),
        ]
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан — заполни файл .env (см. .env.example)")

    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Порядок важен: админский роутер первым (он ограничен фильтром по ADMIN_IDS),
    # затем регистрация, затем клиентский роутер с "catch-all" в конце.
    dp.include_router(admin.router)
    dp.include_router(registration.router)
    dp.include_router(client.router)

    await set_commands(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
