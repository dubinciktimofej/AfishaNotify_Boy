import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any

from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# >>>>>>>>>>>>>>> ВСТАВЬ СЮДА СВОЙ ТОКЕН <<<<<<<<<<<<<<
TOKEN = "8540143885:AAH8dTpvjCYLytE6mHP7KY_T027lHYSKTa8"


# ============= Загрузка событий =============

def load_events() -> List[Dict[str, Any]]:
    """Загружаем events.json и оставляем только Ростов с датой."""
    with open("events.json", "r", encoding="utf-8") as f:
        events = json.load(f)

    events = [
        e for e in events
        if e.get("city_slug") == "rnd" and e.get("date_iso")
    ]

    events.sort(key=lambda e: e["date_iso"])
    return events


EVENTS = load_events()

# user_id -> список напоминаний
# каждый элемент: {"task": asyncio.Task, "event": {...}, "notify_dt": datetime}
USER_EVENTS: Dict[int, List[Dict[str, Any]]] = {}


# ============= Клавиатура-меню =============

def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton("🎟 Афиша концертов")],
        [KeyboardButton("🔔 Мои мероприятия")],
        [KeyboardButton("❌ Отменить напоминания")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ============= Команды =============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я бот-напоминалка по концертам в Ростове-на-Дону 🎵\n\n"
        "Команды:\n"
        "• /events — показать афишу\n"
        "• /my_events — список выбранных концертов\n"
        "• /menu — показать меню\n\n"
        "Используй кнопки внизу, чтобы управлять ботом."
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=get_main_keyboard())


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text(
            "Меню открыто. Выбери действие:",
            reply_markup=get_main_keyboard(),
        )


async def events_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not EVENTS:
        if update.message:
            await update.message.reply_text("Событий не найдено 😢")
        return

    keyboard = []

    for idx, e in enumerate(EVENTS):
        try:
            date_obj = datetime.fromisoformat(e["date_iso"])
            date_str = date_obj.strftime("%d.%m.%Y")
        except Exception:
            date_str = e["date_iso"]

        text = f"{date_str} — {e['title']}"
        keyboard.append([
            InlineKeyboardButton(text, callback_data=f"event:{idx}")
        ])

    if update.message:
        await update.message.reply_text(
            "Выбери мероприятие:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def my_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    items = USER_EVENTS.get(chat_id, [])

    if not items:
        if update.message:
            await update.message.reply_text(
                "У тебя пока нет активных напоминаний.",
                reply_markup=get_main_keyboard(),
            )
        return

    lines = ["Твои активные напоминания:\n"]
    for item in items:
        ev = item["event"]
        notify_dt: datetime = item["notify_dt"]
        try:
            event_date = datetime.fromisoformat(ev["date_iso"]).strftime("%d.%m.%Y")
        except Exception:
            event_date = ev["date_iso"]

        lines.append(
            f"• {ev['title']} ({event_date}), напомню: "
            f"{notify_dt.strftime('%d.%m.%Y %H:%M')}"
        )

    if update.message:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=get_main_keyboard(),
        )


async def cancel_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отменить все напоминания для текущего пользователя."""
    chat_id = update.effective_chat.id
    items = USER_EVENTS.get(chat_id, [])

    if not items:
        if update.message:
            await update.message.reply_text(
                "У тебя нет активных напоминаний.",
                reply_markup=get_main_keyboard(),
            )
        return

    # отменяем все asyncio-задачи
    for item in items:
        task: asyncio.Task = item["task"]
        task.cancel()

    USER_EVENTS[chat_id] = []

    if update.message:
        await update.message.reply_text(
            "Все твои напоминания отменены ❌",
            reply_markup=get_main_keyboard(),
        )


# ============= Обработка текстовых кнопок меню =============

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = (update.message.text or "").strip()

    if text == "🎟 Афиша концертов":
        await events_list(update, context)
    elif text == "🔔 Мои мероприятия":
        await my_events(update, context)
    elif text == "❌ Отменить напоминания":
        await cancel_all(update, context)
    else:
        await update.message.reply_text(
            "Я тебя не понял. Нажми кнопку внизу или команду /menu.",
            reply_markup=get_main_keyboard(),
        )


# ============= Фоновая задача с напоминанием =============

async def reminder_task(bot, chat_id: int, event: Dict[str, Any], delay_seconds: float):
    try:
        # ждём до нужного момента
        await asyncio.sleep(delay_seconds)
    except asyncio.CancelledError:
        # если напоминание отменили — просто выходим
        return

    text = (
        f"🔔 Напоминание!\n\n"
        f"Уже завтра концерт:\n"
        f"🎤 {event['title']}\n"
        f"📍 {event['venue']}\n"
        f"📅 {event['date_iso']}\n\n"
        f"Ссылка: {event['url']}"
    )

    await bot.send_message(chat_id=chat_id, text=text)


# ============= Выбор события (inline-кнопки) =============

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return

    await query.answer()

    data = query.data or ""
    if not data.startswith("event:"):
        return

    idx = int(data.split(":", 1)[1])
    if idx < 0 or idx >= len(EVENTS):
        await query.edit_message_text("Не нашёл это событие :(")
        return

    event = EVENTS[idx]
    date_iso = event["date_iso"]
    event_date = datetime.fromisoformat(date_iso)

    # уведомление за 1 день в 10:00
    notify_dt = event_date - timedelta(days=1)
    notify_dt = notify_dt.replace(hour=10, minute=0, second=0, microsecond=0)

    now = datetime.now()
    if notify_dt <= now:
        await query.edit_message_text(
            f"Для события «{event['title']}» уже поздно ставить напоминание 😢"
        )
        return

    chat_id = query.message.chat_id

    delay = (notify_dt - now).total_seconds()

    # создаём фоновую задачу
    task = context.application.create_task(
        reminder_task(context.application.bot, chat_id, event, delay)
    )

    # сохраняем напоминание в памяти
    items = USER_EVENTS.setdefault(chat_id, [])
    items.append({
        "task": task,
        "event": event,
        "notify_dt": notify_dt,
    })

    await query.edit_message_text(
        f"Окей! Напомню за день до концерта:\n\n"
        f"🎤 {event['title']}\n"
        f"📅 {date_iso}\n"
        f"📍 {event['venue']}"
    )


# ============= MAIN =============

def main():
    application = Application.builder().token(TOKEN).build()

    # команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", show_menu))
    application.add_handler(CommandHandler("events", events_list))
    application.add_handler(CommandHandler("my_events", my_events))
    application.add_handler(CommandHandler("cancel", cancel_all))

    # текстовые сообщения (кнопки меню)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    # inline-кнопки (выбор концерта)
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()


if __name__ == "__main__":
    main()
