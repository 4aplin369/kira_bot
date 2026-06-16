# -*- coding: utf-8 -*-
"""
Телеграм-бот для беременной подруги. Версия 2 (в разработке).

Что умеет:
  🌅 Доброе утро      — тёплое сообщение и комплимент
  👶 Размер малыша    — по текущей неделе (с фруктом/овощем), с листанием недель
  ⏳ Обратный отсчёт  — сколько дней до встречи с малышом
  🔍 Можно / нельзя   — еда, кофе, лекарства, спорт
  ✅ Чек-листы        — вопросы врачу, анализы, дела по триместрам
  🦶 Шевеления        — счётчик (пока в рамках захода; память — следующий шаг)

Дата родов общая для всех — DUE_DATE (берётся из .env, дефолт — дата Ксюши).
Версия 2 добавляет хранение (SQLite, см. db.py): пользователи регистрируются
в БД, поверх которой будут строиться дневник, фото и счётчик с памятью.
"""

import os
import random
import logging
from datetime import date, time, timezone, timedelta

from dotenv import load_dotenv

# Подхватываем переменные из файла .env (если он есть рядом со скриптом).
load_dotenv()

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

import content
import db

# ─────────────────────────────────────────────────────────────────────
# НАСТРОЙКИ — все значения берутся из .env (см. .env.example)
# ─────────────────────────────────────────────────────────────────────
def _parse_date(value: str, default: date) -> date:
    """Парсит дату вида ГГГГ-ММ-ДД из .env; при ошибке — значение по умолчанию."""
    if not value:
        return default
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        logging.warning("Не удалось разобрать дату %r, использую %s", value, default)
        return default


def _parse_ids(value: str) -> set[int]:
    """Парсит набор Telegram ID из строки вида '123, 456'."""
    if not value:
        return set()
    return {int(x) for x in value.replace(",", " ").split()}


# Токен бота от @BotFather.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Предполагаемая дата родов (ПДР), формат ГГГГ-ММ-ДД.
DUE_DATE = _parse_date(os.environ.get("DUE_DATE", ""), date(2026, 10, 26))

# Роли по Telegram ID (через запятую).
# ADMIN_IDS — тестировщик: видит всё, включая будущие функции (дневник и т.п.).
# FRIEND_IDS — подруга (стабильная версия).
ADMIN_IDS = _parse_ids(os.environ.get("ADMIN_IDS", "")) or {122879776}
FRIEND_IDS = _parse_ids(os.environ.get("FRIEND_IDS", "")) or {78689009}

# Имя подруги — используется в обращениях в текстах.
FRIEND_NAME = os.environ.get("FRIEND_NAME", "Ксюша")

PREGNANCY_DAYS = 280  # 40 недель

# Автоматическое «Доброе утро».
MORNING_TZ = timezone(timedelta(hours=3))   # Москва, UTC+3 (без перехода на лето)
MORNING_TIME = time(9, 0, tzinfo=MORNING_TZ)

# Кому слать автоутро: подруге и админам (без дублей).
MORNING_RECIPIENTS = ADMIN_IDS | FRIEND_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def role_for(user_id: int) -> str:
    if is_admin(user_id):
        return "admin"
    if user_id in FRIEND_IDS:
        return "friend"
    return "other"


logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)

# ─────────────────────────────────────────────────────────────────────
# Расчёт срока (от общей даты родов DUE_DATE)
# ─────────────────────────────────────────────────────────────────────
def days_left() -> int:
    return (DUE_DATE - date.today()).days


def current_week() -> int:
    """Текущая акушерская неделя (1–40+)."""
    gestational_days = PREGNANCY_DAYS - days_left()
    week = gestational_days // 7
    return max(1, week)


def trimester(week: int) -> str:
    if week <= 13:
        return "первый триместр"
    if week <= 27:
        return "второй триместр"
    return "третий триместр"


# ─────────────────────────────────────────────────────────────────────
# Клавиатуры
# ─────────────────────────────────────────────────────────────────────
def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    """Главное меню, собирается под роль.

    У подруги скрыты «Доброе утро» (толку от кнопки нет — авто-рассылка
    в 9:00 всё равно приходит) и «Шевеления» (вернём в Версии 2 с базой).
    """
    admin = is_admin(user_id)
    buttons = []
    if admin:
        buttons.append("🌅 Доброе утро")
    buttons += ["👶 Размер малыша", "⏳ Обратный отсчёт", "🔍 Можно / нельзя", "✅ Чек-листы"]
    if admin:
        buttons.append("🦶 Шевеления")
    # Раскладываем по 2 кнопки в ряд.
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def week_keyboard(week: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    if week > min(content.WEEKS):
        row.append(InlineKeyboardButton("◀ Предыдущая", callback_data=f"week:{week-1}"))
    if week < max(content.WEEKS):
        row.append(InlineKeyboardButton("Следующая ▶", callback_data=f"week:{week+1}"))
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("📍 Текущая неделя", callback_data="week:current")])
    return InlineKeyboardMarkup(buttons)


SAFETY_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🍽 Еда", callback_data="safety:food"),
         InlineKeyboardButton("☕ Кофе", callback_data="safety:coffee")],
        [InlineKeyboardButton("💊 Лекарства", callback_data="safety:meds"),
         InlineKeyboardButton("🏃 Спорт", callback_data="safety:sport")],
    ]
)

CHECKLIST_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("🩺 Вопросы врачу", callback_data="check:doctor")],
        [InlineKeyboardButton("🧪 Анализы и скрининги", callback_data="check:tests")],
        [InlineKeyboardButton("🌿 Дела: 2 триместр", callback_data="check:second")],
        [InlineKeyboardButton("🤍 Дела: 3 триместр", callback_data="check:third")],
    ]
)

# Тексты-подсказки меню (используются и при показе, и при возврате «Назад»).
SAFETY_PROMPT = "Что тебя интересует? Выбери раздел 👇"
CHECKLIST_PROMPT = "Выбери чек-лист 👇"

# Кнопки «Назад» к соответствующим меню.
BACK_TO_SAFETY = InlineKeyboardMarkup(
    [[InlineKeyboardButton("◀ Назад к разделам", callback_data="safety:menu")]]
)
BACK_TO_CHECKLISTS = InlineKeyboardMarkup(
    [[InlineKeyboardButton("◀ Назад к чек-листам", callback_data="check:menu")]]
)


def moves_keyboard(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ Малыш толкнулся", callback_data="move:add")],
            [InlineKeyboardButton("🔄 Сбросить", callback_data="move:reset")],
        ]
    )


def moves_text(count: int) -> str:
    return (
        "🦶 *Счётчик шевелений*\n\n"
        f"Насчитано: *{count}*\n\n"
        "Жми «➕ Малыш толкнулся» каждый раз, когда чувствуешь толчок. "
        "Число запоминается — обнулить можно кнопкой «🔄 Сбросить»."
    )


# ─────────────────────────────────────────────────────────────────────
# Тексты-карточки
# ─────────────────────────────────────────────────────────────────────
def baby_size_text(week: int) -> str:
    data = content.WEEKS.get(week)
    if not data:
        # за пределами таблицы — показываем крайнюю
        week = max(content.WEEKS) if week > max(content.WEEKS) else min(content.WEEKS)
        data = content.WEEKS[week]
    fruit, size, note = data
    return (
        f"*Неделя {week}* · {trimester(week)}\n\n"
        f"Малыш размером с {fruit}\n"
        f"📏 {size}\n\n"
        f"{note}"
    )


def countdown_text() -> str:
    d = days_left()
    week = current_week()
    if d > 0:
        weeks = d // 7
        days = d % 7
        tail = f"≈ {weeks} нед." + (f" {days} дн." if days else "")
        return (
            f"⏳ *До встречи с малышом*\n\n"
            f"Осталось *{d}* дней ({tail})\n\n"
            f"Сейчас {week}-я неделя, {trimester(week)}.\n"
            f"Дата встречи: {DUE_DATE.strftime('%d.%m.%Y')} 💛"
        )
    elif d == 0:
        return "⏳ Сегодня та самая дата! Малыш может появиться со дня на день. 💛"
    else:
        return "⏳ Дата уже позади — возможно, малыш уже с вами! Поздравляю! 🎉💛"


# ─────────────────────────────────────────────────────────────────────
# Хендлеры
# ─────────────────────────────────────────────────────────────────────
def _hello(user_id: int) -> str:
    """Обращение в приветствии: подругу зовём по имени, остальных — ласково."""
    return FRIEND_NAME if user_id in FRIEND_IDS else "дорогая"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    db.upsert_user(uid, update.effective_user.first_name or "", role_for(uid))
    week = current_week()
    text = (
        f"Привет, {_hello(uid)}! 💛\n\n"
        "Это маленький бот-сюрприз, чтобы быть рядом с тобой в эти особенные месяцы. "
        "Он будет поддерживать тебя добрым словом, рассказывать, как растёт малыш, "
        "и помогать с полезными мелочами.\n\n"
        f"Сейчас у тебя примерно *{week}-я неделя* — {trimester(week)}.\n\n"
        "Загляни в меню внизу 👇 Всё уже работает."
    )
    if is_admin(uid):
        text += "\n\n_🔧 Режим тестировщика: тебе будут доступны будущие функции (дневник и пр.)._"
    await update.message.reply_markdown(text, reply_markup=build_main_keyboard(uid))


async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    role = "тестировщик 🔧" if is_admin(uid) else "обычный пользователь"
    await update.message.reply_text(f"Твой Telegram ID: {uid}\nРоль: {role}")


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text
    uid = update.effective_user.id

    if msg == "🌅 Доброе утро" and is_admin(uid):
        await update.message.reply_text(random.choice(content.GREETINGS))

    elif msg == "👶 Размер малыша":
        week = current_week()
        await update.message.reply_markdown(
            baby_size_text(week), reply_markup=week_keyboard(week)
        )

    elif msg == "⏳ Обратный отсчёт":
        await update.message.reply_markdown(countdown_text())

    elif msg == "🔍 Можно / нельзя":
        await update.message.reply_text(SAFETY_PROMPT, reply_markup=SAFETY_KEYBOARD)

    elif msg == "✅ Чек-листы":
        await update.message.reply_text(CHECKLIST_PROMPT, reply_markup=CHECKLIST_KEYBOARD)

    elif msg == "🦶 Шевеления" and is_admin(uid):
        # Пока только для админа (Версия 2 — с базой для всех).
        # Не обнуляем — показываем накопленный счёт. Сброс только кнопкой.
        count = context.user_data.get("moves", 0)
        await update.message.reply_text(
            moves_text(count),
            parse_mode="Markdown",
            reply_markup=moves_keyboard(count),
        )

    else:
        await update.message.reply_text(
            "Я тут 💛 Выбери что-нибудь из меню внизу.",
            reply_markup=build_main_keyboard(uid),
        )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("week:"):
        arg = data.split(":", 1)[1]
        week = current_week() if arg == "current" else int(arg)
        await query.edit_message_text(
            baby_size_text(week),
            parse_mode="Markdown",
            reply_markup=week_keyboard(week),
        )

    elif data.startswith("safety:"):
        key = data.split(":", 1)[1]
        if key == "menu":
            # Возврат к списку разделов.
            await query.edit_message_text(SAFETY_PROMPT, reply_markup=SAFETY_KEYBOARD)
        else:
            await query.edit_message_text(
                content.SAFETY[key],
                parse_mode="Markdown",
                reply_markup=BACK_TO_SAFETY,
            )

    elif data.startswith("check:"):
        key = data.split(":", 1)[1]
        if key == "menu":
            # Возврат к списку чек-листов.
            await query.edit_message_text(CHECKLIST_PROMPT, reply_markup=CHECKLIST_KEYBOARD)
        else:
            await query.edit_message_text(
                content.CHECKLISTS[key],
                parse_mode="Markdown",
                reply_markup=BACK_TO_CHECKLISTS,
            )

    elif data.startswith("move:"):
        action = data.split(":", 1)[1]
        if action == "add":
            context.user_data["moves"] = context.user_data.get("moves", 0) + 1
        elif action == "reset":
            context.user_data["moves"] = 0
        count = context.user_data.get("moves", 0)
        # Показываем число прямо в тексте — так видно, что счётчик растёт.
        await query.answer(f"Засчитано: {count}")
        try:
            await query.edit_message_text(
                moves_text(count),
                parse_mode="Markdown",
                reply_markup=moves_keyboard(count),
            )
        except Exception:
            # "Message is not modified" и т.п. — не критично.
            pass


async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    """Ежедневная авто-отправка «Доброе утро» получателям из MORNING_RECIPIENTS."""
    for chat_id in MORNING_RECIPIENTS:
        try:
            greeting = random.choice(content.GREETINGS)
            # Подруге — личное обращение по имени.
            if chat_id in FRIEND_IDS:
                greeting = f"Доброе утро, {FRIEND_NAME}! 💛\n\n{greeting}"
            await context.bot.send_message(chat_id, greeting)
        except Exception as e:
            # Один недоступный адресат (бот заблокирован, чат не начат) не должен
            # ломать рассылку остальным.
            logging.warning("Не смог отправить утро для %s: %s", chat_id, e)


def main():
    if not BOT_TOKEN:
        raise SystemExit(
            "Не задан токен бота. Создай файл .env рядом с main.py "
            "и впиши в него строку BOT_TOKEN=твой_токен_от_BotFather "
            "(шаблон — в .env.example)."
        )
    db.init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", whoami))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    # Ежедневное «Доброе утро» в 9:00 по Москве.
    app.job_queue.run_daily(morning_job, time=MORNING_TIME, name="morning")

    logging.info(
        "Бот запущен. Автоутро в %s для %s.",
        MORNING_TIME.strftime("%H:%M %Z"), MORNING_RECIPIENTS,
    )
    app.run_polling()


if __name__ == "__main__":
    main()
