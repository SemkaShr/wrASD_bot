import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, THRESHOLDS
from db import conn, cursor, get_chat_settings, set_chat_field, ensure_chat
from filters import SpamFilter, spam_pipeline
from keyboards import private_start_keyboard, threshold_keyboard

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.MARKDOWN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


async def is_user_admin(chat: types.Chat, user_id: int) -> bool:
    try:
        admins = await chat.get_administrators()
        return user_id in [a.user.id for a in admins]
    except Exception as e:
        logger.exception("Failed to get admins for chat %s: %s", getattr(chat, "id", None), e)
        return False


def increment_warning(chat_id: int, user_id: int) -> int:
    try:
        cursor.execute(
            "INSERT INTO warnings(chat_id, user_id, count) VALUES(?,?,1) "
            "ON CONFLICT(chat_id,user_id) DO UPDATE SET count=count+1",
            (chat_id, user_id)
        )
        conn.commit()
        cursor.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        row = cursor.fetchone()
        return row[0] if row else 0
    except Exception:
        logger.exception("Failed to increment warning")
        return 0


def reset_warnings(chat_id: int, user_id: int):
    try:
        cursor.execute("DELETE FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id))
        conn.commit()
    except Exception:
        logger.exception("Failed to reset warnings")


def add_banned(chat_id: int, user_id: int, reason: str):
    try:
        cursor.execute("INSERT INTO banned (chat_id, user_id, reason) VALUES (?,?,?)", (chat_id, user_id, reason))
        conn.commit()
    except Exception:
        logger.exception("Failed to add banned entry")


async def private_start(message: types.Message):
    bot_info = await bot.get_me()
    kb = private_start_keyboard(bot_info.username)
    text = (
        "*👋 Привет! Я - анти-фишинг бот для групп.*\n\n"
        "*Что я умею:*\n"
        "• Автоматически удалять фишинговые сообщения с использованием машинного обучения.\n"
        "• В случае несрабатывения, администратор может пометить сообщение командой /report (reply).\n"
        "• Настройки: порог детекции, логирование, анонимные репорты, наказания.\n\n"
        "*Как использовать:*\n"
        "1. Нажмите «Добавить в группу» и добавьте бота в вашу группу.\n"
        "2. Выдайте боту права администратора: удаление сообщений, бан/ограничение пользователей.\n\n"
        "*Команды:*\n"
        "• `/threshold` - открыть меню порогов (weak/normal/high).\n"
        "• `/report` - ответьте на сообщение и отправьте /report, чтобы пометить его как спам.\n"
        "• `/anon_reports on|off` - включить/выключить анонимные репорты.\n"
        "• `/punishment warn|mute|ban` - установить действие при превышении предупреждений.\n"
        "• `/stats` - статистика удалений/репортов.\n"
        "• `/banned` - список забаненных (в базе).\n"
        "• `/logging on|off` - включить/выключить логирование ML-результатов.\n\n"
    )
    await message.answer(text, reply_markup=kb)


dp.message.register(private_start, F.chat.type == "private")


async def on_my_chat_member(update: types.ChatMemberUpdated):
    chat = update.chat
    new_status = update.new_chat_member.status
    if new_status in ("member", "administrator"):
        try:
            await bot.send_message(
                chat.id,
                "👋 Спасибо, что добавили меня!\n\n"
                "Чтобы я мог удалять фишинговые сообщения, выдайте мне права администратора:\n"
                "• Удаление сообщений\n"
                "• Бан/ограничение пользователей\n\n"
            )
        except Exception:
            logger.exception("Can't send welcome message to chat %s", chat.id)


dp.my_chat_member.register(on_my_chat_member)

async def handle_spam(message: types.Message):
    chat = message.chat
    user = message.from_user

    settings = get_chat_settings(chat.id)
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete message in chat %s", chat.id)

    warns = increment_warning(chat.id, user.id)
    max_warns = settings["max_warnings"]
    punishment = settings["punishment"]

    try:
        await message.answer(
            f"⚠️ Сообщение от {user.full_name} удалено.\n"
            f"Предупреждение #{warns} / {max_warns}."
        )
    except Exception:
        logger.exception("Failed to send warning message")

    if warns >= max_warns:
        reason = "Reached warnings (ML)" 
        try:
            if punishment == "ban":
                await bot.ban_chat_member(chat.id, user.id)
                add_banned(chat.id, user.id, reason)
                await message.answer(f"⛔ Пользователь {user.full_name} забанен (достиг лимита предупреждений).")
            elif punishment == "mute":
                await bot.restrict_chat_member(
                    chat.id,
                    user.id,
                    permissions=types.ChatPermissions(can_send_messages=False)
                )
                add_banned(chat.id, user.id, "muted: reached warnings")
                await message.answer(f"🔇 Пользователь {user.full_name} лишился голоса (достиг лимита предупреждений).")
            else:
                await message.answer(f"⚠️ Пользователь {user.full_name} достиг лимита предупреждений, но действия нет.")
            reset_warnings(chat.id, user.id)
        except Exception:
            logger.exception("Failed to apply punishment for user %s in chat %s", user.id, chat.id)

dp.message.register(handle_spam, F.text, SpamFilter())

async def report_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Команда /report работает только в группах.")
        return

    if not message.reply_to_message:
        await message.reply("ℹ️ Использование: ответьте на сообщение, затем отправьте /report.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Команда доступна только администраторам.")
        return

    original = message.reply_to_message
    text = original.text or original.caption or ""
    ml_prob = None
    if spam_pipeline is not None and text:
        try:
            ml_prob = float(spam_pipeline.predict_proba([text])[0][1])
        except Exception:
            try:
                ml_prob = float(spam_pipeline.predict([text])[0])
            except Exception:
                ml_prob = None

    settings = get_chat_settings(message.chat.id)
    reporter_id = None if settings["anon_reports"] else message.from_user.id

    try:
        cursor.execute(
            "INSERT INTO reports (chat_id, message_text, spam_prob, reporter_id) VALUES (?,?,?,?)",
            (message.chat.id, text, ml_prob, reporter_id)
        )
        conn.commit()
    except Exception:
        logger.exception("Failed to insert report to DB")

    try:
        await original.delete()
    except Exception:
        logger.exception("Failed to delete reported message")

    await message.reply("✅ Сообщение помечено как спам и сохранено в репортах.")


dp.message.register(report_cmd, Command(commands=["report"]))


async def threshold_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Эта команда доступна только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только администраторы могут менять порог.")
        return

    await message.answer(
        "*Выберите уровень детекции (чувствительность):*\n\n"
        "🟢 Weak - агрессивный (много ложных срабатываний)\n"
        "🟡 Normal - сбалансированный\n"
        "🔴 High - строгий (только явный спам)",
        reply_markup=threshold_keyboard()
    )


dp.message.register(threshold_cmd, Command(commands=["threshold"]))


async def threshold_callback(call: types.CallbackQuery):
    await call.answer()
    data = call.data or ""
    if not data.startswith("threshold_"):
        return

    level = data.split("_", 1)[1]
    mapping = {"weak": THRESHOLDS["weak"], "normal": THRESHOLDS["normal"], "high": THRESHOLDS["high"]}
    if level not in mapping:
        await call.message.answer("Неизвестный уровень.")
        return

    chat = call.message.chat
    if chat.type != "private":
        if not await is_user_admin(chat, call.from_user.id):
            await call.message.answer("Только администраторы могут менять настройки.")
            return

    set_chat_field(chat.id, "threshold", mapping[level])
    await call.message.edit_text(f"✅ Порог установлен: *{level.upper()}* ({mapping[level]})", parse_mode=ParseMode.MARKDOWN)


dp.callback_query.register(threshold_callback, lambda c: c.data and c.data.startswith("threshold_"))

async def anon_reports_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Эта команда работает только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только администратор может менять настройку.")
        return

    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await message.reply("Использование: `/anon_reports on` или `/anon_reports off`", parse_mode=ParseMode.MARKDOWN)
        return

    value = 1 if parts[1].lower() == "on" else 0
    set_chat_field(message.chat.id, "anon_reports", value)
    await message.reply(f"✅ Анонимные репорты {'включены' if value else 'выключены'}.")


dp.message.register(anon_reports_cmd, Command(commands=["anon_reports"]))

async def logging_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Эта команда работает только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только администратор может менять настройку.")
        return

    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        await message.reply("Использование: `/logging on` или `/logging off`", parse_mode=ParseMode.MARKDOWN)
        return

    value = 1 if parts[1].lower() == "on" else 0
    set_chat_field(message.chat.id, "logging", value)
    await message.reply(f"✅ Логирование ML {'включено' if value else 'выключено'}.")


dp.message.register(logging_cmd, Command(commands=["logging"]))

async def punishment_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Эта команда работает только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только администратор может менять настройку.")
        return

    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("warn", "mute", "ban"):
        await message.reply("Использование: `/punishment warn|mute|ban`")
        return

    val = parts[1].lower()
    if val == "warn":
        set_chat_field(message.chat.id, "punishment", "warn")
    elif val == "mute":
        set_chat_field(message.chat.id, "punishment", "mute")
    else:
        set_chat_field(message.chat.id, "punishment", "ban")

    await message.reply(f"✅ Тип наказания установлен: *{val}*.", parse_mode=ParseMode.MARKDOWN)


dp.message.register(punishment_cmd, Command(commands=["punishment"]))

async def stats_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Команда доступна только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только админ может просматривать статистику.")
        return

    chat_id = message.chat.id
    cursor.execute("SELECT COUNT(*) FROM ml_logs WHERE chat_id=? AND is_deleted=1", (chat_id,))
    deleted = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM reports WHERE chat_id=?", (chat_id,))
    reports = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM banned WHERE chat_id=?", (chat_id,))
    banned_count = cursor.fetchone()[0] or 0

    await message.reply(
        f"📊 *Статистика чата*\n\n"
        f"🗑️ Удалено сообщений: `{deleted}`\n"
        f"📝 Репортов: `{reports}`\n"
        f"⛔ Забанено: `{banned_count}`",
        parse_mode=ParseMode.MARKDOWN
    )

dp.message.register(stats_cmd, Command(commands=["stats"]))

async def banned_cmd(message: types.Message):
    if message.chat.type == "private":
        await message.reply("Команда доступна только в группах.")
        return

    if not await is_user_admin(message.chat, message.from_user.id):
        await message.reply("❌ Только админ может просматривать список забаненных.")
        return

    chat_id = message.chat.id
    cursor.execute("SELECT user_id, reason, created_at FROM banned WHERE chat_id=?", (chat_id,))
    rows = cursor.fetchall()
    if not rows:
        await message.reply("Пока никто не забанен (в базе).")
        return

    text_lines = ["⛔ *Список забаненных (в базе):*"]
    for uid, reason, created in rows:
        text_lines.append(f"- `{uid}` - {reason} (в {created})")
    await message.reply("\n".join(text_lines), parse_mode=ParseMode.MARKDOWN)


dp.message.register(banned_cmd, Command(commands=["banned"]))

async def show_commands_callback(call: types.CallbackQuery):
    await call.answer()
    text = (
        "*Команды и кнопки:*\n\n"
        "• `/settings` - текущие настройки\n"
        "• `/threshold` - выбрать порог (weak/normal/high).\n"
        "• `/report` - ответьте на сообщение и отправьте /report (админ).\n"
        "• `/anon_reports on|off` - включить/выключить анонимные репорты.\n"
        "• `/punishment warn|mute|ban` - тип наказания после превышения предупреждений.\n"
        "• `/stats` - статистика (только админы).\n"
        "• `/banned` - список забаненных (только админы).\n"
        "• `/logging on|off` - вкл/выкл логирование ML результатов.\n\n"
    )
    await call.message.answer(text, parse_mode=ParseMode.MARKDOWN)


dp.callback_query.register(show_commands_callback, lambda c: c.data == "commands")

def threshold_to_level(threshold: float) -> str:
    if threshold <= 0.8:
        return "🟢 Weak"
    elif threshold <= 0.9:
        return "🟡 Normal"
    return "🔴 High"

async def settings_cmd(message: types.Message):
    if not await is_user_admin(message.chat, message.from_user.id):
        return

    settings = get_chat_settings(message.chat.id)

    await message.answer(
        "*⚙️ Текущие настройки чата*\n\n"
        f"🧠 *ML порог:* `{settings['threshold']}`\n"
        f"🎯 *Уровень:* {threshold_to_level(settings['threshold'])}\n\n"
        f"🕵️ *Анонимные репорты:* {'✅ Включены' if settings['anon_reports'] else '❌ Отключены'}\n"
        f"📄 *Логирование:* {'✅ Включено' if settings['logging'] else '❌ Отключено'}\n\n"
        f"⚠️ *Макс. предупреждений:* `{settings['max_warnings']}`\n"
        f"🚫 *Наказание:* `{settings['punishment']}`\n\n"
    )

dp.message.register(settings_cmd, F.text == "/settings")

async def main():
    logger.info("Starting bot...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
