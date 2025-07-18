import logging
import os
import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import telebot
from telebot import types
from math import radians, cos, sin, asin, sqrt

# Load environment variables
load_dotenv()

token = os.getenv("BOT_TOKEN")
admin_id = int(os.getenv("ADMIN_ID", "0"))  # admin Telegram ID

db_config = {
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST"),
    'port': os.getenv("DB_PORT"),
}

# Geo target settings
TARGET_LAT = float(os.getenv("TARGET_LAT", "41.356015"))
TARGET_LON = float(os.getenv("TARGET_LON", "69.314663"))
RADIUS_METERS = float(os.getenv("RADIUS_METERS", "150"))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Initialize bot
bot = telebot.TeleBot(token)

# Database connection helper
def get_db_connection():
    return psycopg2.connect(**db_config)

# Distance calculation
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# Keyboards
def main_menu_markup(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Подтвердить участие", "📊 Мои баллы")
    if user_id == admin_id:
        markup.add("✉️ Рассылка (админ)", "🖼️ Фото всем", "📹 Видео всем", "📎 Файл всем", "📍 Локация всем", "⚙️ Изменить локацию")
    return markup

def location_request_markup():
    kb = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    kb.add(types.KeyboardButton(text="📍 Отправить геолокацию", request_location=True))
    return kb

# /start handler
@bot.message_handler(commands=['start'])
def command_start(message):
    uid = message.from_user.id
    name = message.from_user.first_name or message.from_user.username
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (uid,))
            if not cur.fetchone():
                cur.execute("INSERT INTO users (user_id, name) VALUES (%s, %s)", (uid, name))
                conn.commit()
    bot.send_message(
        message.chat.id,
        f"Привет, {name}! Добро пожаловать в YES+ 🎉\n20 баллов за участие в тимбилдинге.",
        reply_markup=main_menu_markup(uid)
    )

# /score handler
@bot.message_handler(commands=['score'])
def command_score(message):
    uid = message.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (uid,))
            res = cur.fetchone()
    if res:
        bot.send_message(message.chat.id, f"У тебя {res[0]} баллов 🟢", reply_markup=main_menu_markup(uid))
    else:
        bot.send_message(message.chat.id, "Ты ещё не зарегистрирован. Напиши /start.")

# Button handlers
@bot.message_handler(func=lambda m: m.text == "📊 Мои баллы")
def btn_score(m):
    command_score(m)

@bot.message_handler(func=lambda m: m.text == "✅ Подтвердить участие")
def btn_confirm(m):
    bot.send_message(m.chat.id, "Пожалуйста, отправь свою геолокацию, чтобы подтвердить участие:", reply_markup=location_request_markup())

# Admin broadcast state container
broadcast_state = {}

# Text broadcast
def start_broadcast_text(m):
    broadcast_state[m.chat.id] = {'action': 'text', 'step': 1}
    bot.send_message(m.chat.id, "Введите текст для рассылки:")

@bot.message_handler(func=lambda m: m.text == "✉️ Рассылка (админ)" and m.from_user.id == admin_id)
def admin_broadcast(m):
    start_broadcast_text(m)

@bot.message_handler(func=lambda m: broadcast_state.get(m.chat.id, {}).get('action') == 'text')
def process_broadcast_text(m):
    state = broadcast_state[m.chat.id]
    if state['step'] == 1:
        state['text'] = m.text
        state['step'] = 2
        bot.send_message(m.chat.id, "Подтвердите рассылку текста? (да/нет)")
    else:
        if m.text.lower() == 'да':
            cnt = 0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users = cur.fetchall()
            for (uid,) in users:
                try:
                    bot.send_message(uid, state['text'])
                    cnt += 1
                except:
                    pass
            bot.send_message(m.chat.id, f"Рассылка завершена: {cnt}")
        else:
            bot.send_message(m.chat.id, "Рассылка отменена.")
        broadcast_state.pop(m.chat.id)

# Photo broadcast
@bot.message_handler(func=lambda m: m.text == "🖼️ Фото всем" and m.from_user.id == admin_id)
def admin_broadcast_photo(m):
    broadcast_state[m.chat.id] = {'action':'photo','step':1}
    bot.send_message(m.chat.id, "Пришлите фото или URL:")

@bot.message_handler(content_types=['photo','text'])
def process_broadcast_photo(m):
    state = broadcast_state.get(m.chat.id)
    if not state or state['action'] != 'photo': return
    if state['step'] == 1:
        if m.photo:
            state['photo_id'] = m.photo[-1].file_id
        else:
            state['photo_url'] = m.text
        state['step'] = 2
        bot.send_message(m.chat.id, "Введите подпись (или 'нет'):")
    else:
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'photo_id' in state:
                    bot.send_photo(uid, state['photo_id'], caption=caption)
                else:
                    bot.send_photo(uid, state['photo_url'], caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Фото разослано: {cnt}")
        broadcast_state.pop(m.chat.id)

# Video broadcast
@bot.message_handler(func=lambda m: m.text == "📹 Видео всем" and m.from_user.id == admin_id)
def admin_broadcast_video(m):
    broadcast_state[m.chat.id] = {'action':'video','step':1}
    bot.send_message(m.chat.id, "Пришлите видео или URL:")

@bot.message_handler(content_types=['video','text'])
def process_broadcast_video(m):
    state = broadcast_state.get(m.chat.id)
    if not state or state['action'] != 'video': return
    if state['step'] == 1:
        if m.video:
            state['video_id'] = m.video.file_id
        else:
            state['video_url'] = m.text
        state['step'] = 2
        bot.send_message(m.chat.id, "Введите подпись (или 'нет'):")
    else:
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'video_id' in state:
                    bot.send_video(uid, state['video_id'], caption=caption)
                else:
                    bot.send_video(uid, state['video_url'], caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Видео разослано: {cnt}")
        broadcast_state.pop(m.chat.id)

# File broadcast
@bot.message_handler(func=lambda m: m.text == "📎 Файл всем" and m.from_user.id == admin_id)
def admin_broadcast_file(m):
    broadcast_state[m.chat.id] = {'action':'file','step':1}
    bot.send_message(m.chat.id, "Пришлите файл или ссылку:")

@bot.message_handler(content_types=['document','text'])
def process_broadcast_file(m):
    state = broadcast_state.get(m.chat.id)
    if not state or state['action'] != 'file': return
    if state['step'] == 1:
        if m.document:
            state['doc_id'] = m.document.file_id
        else:
            state['doc_url'] = m.text
        state['step'] = 2
        bot.send_message(m.chat.id, "Введите подпись (или 'нет'):")
    else:
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'doc_id' in state:
                    bot.send_document(uid, state['doc_id'], caption=caption)
                else:
                    bot.send_document(uid, state['doc_url'], caption=caption)
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Файл разослан: {cnt}")
        broadcast_state.pop(m.chat.id)

# Location broadcast and changing event location
@bot.message_handler(func=lambda m: m.text == "📍 Локация всем" and m.from_user.id == admin_id)
def admin_broadcast_location(m):
    broadcast_state[m.chat.id] = {'action':'loc','step':1}
    bot.send_message(m.chat.id, "Отправьте локацию для рассылки:", reply_markup=location_request_markup())

@bot.message_handler(func=lambda m: broadcast_state.get(m.chat.id, {}).get('action') == 'loc')
def process_broadcast_location(m):
    state = broadcast_state.get(m.chat.id)
    if m.content_type == 'location' and state['step'] == 1:
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
    state and broadcast_state.pop(m.chat.id)

# Change event location
@bot.message_handler(func=lambda m: m.text == "⚙️ Изменить локацию" and m.from_user.id == admin_id)
def admin_set_location(m):
    bot.send_message(m.chat.id, "Введите новые координаты и радиус через пробел: lat lon radius")
    broadcast_state[m.chat.id] = {'action':'setloc','step':1}

@bot.message_handler(func=lambda m: broadcast_state.get(m.chat.id, {}).get('action') == 'setloc')
def process_set_location(m):
    text = m.text.strip().split()
    try:
        lat, lon, radius = map(float, text)
        global TARGET_LAT, TARGET_LON, RADIUS_METERS
        TARGET_LAT, TARGET_LON, RADIUS_METERS = lat, lon, radius
        bot.send_message(m.chat.id, f"Новая локация: {lat}, {lon}, радиус {radius}м")
    except:
        bot.send_message(m.chat.id, "Неверный формат. Используйте: lat lon radius")
    broadcast_state.pop(m.chat.id, None)

# General location handler for participants
@bot.message_handler(content_types=['location'])
def handle_location(message):
    if message.from_user.id == admin_id and broadcast_state.get(message.chat.id, {}).get('action'):
        return  # admin flows above
    uid = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    dist = calculate_distance(lat, lon, TARGET_LAT, TARGET_LON)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points, last_checkin FROM users WHERE user_id = %s", (uid,))
            data = cur.fetchone()
    if not data:
        return bot.send_message(message.chat.id, "Сначала /start.")
    pts, last = data
    today = datetime.date.today()
    if last == today:
        bot.send_message(message.chat.id, "Уже подтвердили сегодня.", reply_markup=main_menu_markup(uid))
    elif dist <= RADIUS_METERS:
        new = pts + 20
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET points=%s, last_checkin=%s WHERE user_id=%s", (new, today, uid)); conn.commit()
        bot.send_message(message.chat.id, "✅ Участие подтверждено!", reply_markup=main_menu_markup(uid))
    else:
        bot.send_message(message.chat.id, "Вне зоны.", reply_markup=main_menu_markup(uid))

# Start polling
if __name__ == '__main__':
    logger.info("Bot polling started")
    bot.infinity_polling(skip_pending=True)

