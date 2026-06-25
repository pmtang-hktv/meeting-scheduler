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
    buttons.append([InlineKeyboardButton("Suggest another date", callback_data="slot:other_date")])
    buttons.append([InlineKeyboardButton("Cancel", callback_data="slot:cancel")])
    return InlineKeyboardMarkup(buttons)


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🆕 New booking", callback_data="menu:new")],
        [InlineKeyboardButton("✏️ Change a booking", callback_data="menu:change")],
    ])


def booking_list_keyboard(meetings: list[dict]) -> InlineKeyboardMarkup:
    """One button per upcoming booking (labelled with its time + purpose)."""
    buttons = [
        [InlineKeyboardButton(label, callback_data=f"editpick:{m['id']}")]
        for m, label in meetings
    ]
    buttons.append([InlineKeyboardButton("Cancel", callback_data="editcancel")])
    return InlineKeyboardMarkup(buttons)


def edit_fields_keyboard(meeting_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 Date & time", callback_data=f"editfield:{meeting_id}:datetime")],
        [InlineKeyboardButton("⏱ Duration", callback_data=f"editfield:{meeting_id}:duration")],
        [InlineKeyboardButton("📍 Location", callback_data=f"editfield:{meeting_id}:location")],
        [InlineKeyboardButton("📝 Purpose", callback_data=f"editfield:{meeting_id}:purpose")],
        [InlineKeyboardButton("👤 Organiser", callback_data=f"editfield:{meeting_id}:organiser")],
        [InlineKeyboardButton("✅ Done", callback_data="editcancel")],
    ])
