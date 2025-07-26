import os
import logging
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import telebot
from telebot import types

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(BOT_TOKEN)
admin_state = {}
broadcast_history = []

# === Подключение к базе данных ===
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# === Проверка администратора ===
def is_admin(user_id):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None

# === Клавиатура администратора ===
def admin_menu_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Текст✉️", "Фото🖼️", "Видео📹")
    kb.add("Файл📎", "Локация📍", "Опрос📊")
    kb.add("Удалить✂️")
    return kb

# === Сопоставление действий ===
action_map = {
    "Текст✉️": "text",
    "Фото🖼️": "photo",
    "Видео📹": "video",
    "Файл📎": "file",
    "Локация📍": "location",
    "Опрос📊": "poll",
    "Удалить✂️": "clear",
}

# === Обработка команды администратора ===
@bot.message_handler(func=lambda m: m.text in action_map and is_admin(m.from_user.id))
def admin_cmd(m):
    action = action_map[m.text]
    admin_state[m.from_user.id] = {
        "action": action,
        "step": 1,
        "data": {}
    }
    if action == "poll":
        bot.send_message(m.chat.id, "Введите вопрос для опроса:")
    else:
        bot.send_message(m.chat.id, "Отправьте содержимое для рассылки")

# === Обработка состояний администратора ===
@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'location'])
def admin_state_handler(m):
    if m.from_user.id not in admin_state:
        return

    state = admin_state[m.from_user.id]
    action = state.get("action")
    step = state.get("step", 1)
    data = state.setdefault("data", {})

    # === ОПРОС ===
    if action == "poll":
        if step == 1:
            data["question"] = m.text.strip()
            state["step"] = 2
            bot.send_message(m.chat.id, "Введите варианты ответов через точку с запятой (например: Да;Нет):")
            return
        elif step == 2:
            options = [opt.strip() for opt in m.text.split(";") if opt.strip()]
            if len(options) < 2:
                bot.send_message(m.chat.id, "❗ Нужно минимум два варианта ответа. Попробуйте ещё раз:")
                return
            data["options"] = options
            state["step"] = 3
            bot.send_message(m.chat.id, f"Вопрос: {data['question']}\nВарианты: {', '.join(options)}\n\nПодтвердить рассылку? (да/нет)")
            return
        elif step == 3:
            if m.text.lower() == "да":
                sent = 0
                failed = 0
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT user_id FROM users")
                        users = cur.fetchall()

                for (uid,) in users:
                    try:
                        msg = bot.send_poll(uid, data["question"], options=data["options"], is_anonymous=False)
                        broadcast_history.append((uid, msg.message_id))
                        sent += 1
                    except Exception:
                        failed += 1
                bot.send_message(m.chat.id, f"✅ Опрос отправлен {sent} пользователям. Ошибок: {failed}.")
            else:
                bot.send_message(m.chat.id, "❌ Рассылка отменена.")
            admin_state.pop(m.from_user.id)
            return

    # === ТЕКСТ ===
    elif action == "text" and m.content_type == "text":
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                bot.send_message(uid, m.text)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Разослано: {cnt}")
        admin_state.pop(m.from_user.id)

    # === ФОТО ===
    elif action == "photo" and m.content_type == "photo":
        file_id = m.photo[-1].file_id
        caption = m.caption or ""
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                bot.send_photo(uid, file_id, caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Фото разослано: {cnt}")
        admin_state.pop(m.from_user.id)

    # === ВИДЕО ===
    elif action == "video" and m.content_type == "video":
        file_id = m.video.file_id
        caption = m.caption or ""
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                bot.send_video(uid, file_id, caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Видео разослано: {cnt}")
        admin_state.pop(m.from_user.id)

    # === ФАЙЛ ===
    elif action == "file" and m.content_type == "document":
        file_id = m.document.file_id
        caption = m.caption or ""
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                bot.send_document(uid, file_id, caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Файл разослан: {cnt}")
        admin_state.pop(m.from_user.id)

    # === ЛОКАЦИЯ ===
    elif action == "location" and m.content_type == "location":
        lat, lon = m.location.latitude, m.location.longitude
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                bot.send_location(uid, lat, lon)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Локация разослана: {cnt}")
        admin_state.pop(m.from_user.id)

# === Удаление состояния ===
@bot.message_handler(func=lambda m: m.text == "Удалить✂️" and is_admin(m.from_user.id))
def clear_state(m):
    admin_state.pop(m.from_user.id, None)
    bot.send_message(m.chat.id, "Состояние сброшено.")

# === Обработка /start ===
@bot.message_handler(commands=['start'])
def start_handler(m):
    user_id = m.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
            conn.commit()
    if is_admin(user_id):
        bot.send_message(m.chat.id, "Вы вошли как администратор", reply_markup=admin_menu_keyboard())
    else:
        bot.send_message(m.chat.id, "Добро пожаловать! Вы подписаны на рассылки.")

# === Запуск ===
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot.polling(none_stop=True)
