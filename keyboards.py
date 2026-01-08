# keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def private_start_keyboard(bot_username: str):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить в группу", url=f"https://t.me/{bot_username}?startgroup=true")],
            [InlineKeyboardButton(text="📖 Команды (описание)", callback_data="commands")]
        ]
    )


def threshold_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Weak (0.8)", callback_data="threshold_weak"),
                InlineKeyboardButton(text="🟡 Normal (0.9)", callback_data="threshold_normal"),
                InlineKeyboardButton(text="🔴 High (0.95)", callback_data="threshold_high"),
            ]
        ]
    )
