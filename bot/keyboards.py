from __future__ import annotations
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def approval_keyboard(confirmation_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve:{confirmation_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject:{confirmation_id}"),
        ]
    ])


def slot_choice_keyboard(slots: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(slot, callback_data=f"slot:{i}:{slot}")]
        for i, slot in enumerate(slots)
    ]
    buttons.append([InlineKeyboardButton("Cancel", callback_data="slot:cancel")])
    return InlineKeyboardMarkup(buttons)
