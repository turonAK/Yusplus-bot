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

# Bot and Database config
token = os.getenv("BOT_TOKEN")
admin_id = int(os.getenv("ADMIN_ID", "0"))  # admin Telegram ID from .env

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
    # Only admin sees broadcast button
    if user_id == admin_id:
        markup.add("✉️ Рассылка (админ)")
    return markup

def location_request_markup():
    kb = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    kb.add(types.KeyboardButton(text="📍 Отправить геолокацию", request_location=True))
    return kb

# /start handler
@bot.message_handler(commands=['start'])
def command_start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name or message.from_user.username
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO users (user_id, name) VALUES (%s, %s)",
                    (user_id, name)
                )
                conn.commit()
    text = (
        f"Привет, {name}! Добро пожаловать в YES+ 🎉\n"
        "20 баллов за участие в тимбилдинге. "
        "Нажми кнопку, когда будешь на месте!"
    )
    bot.send_message(
        message.chat.id,
        text,
        reply_markup=main_menu_markup(user_id)
    )

# /score handler
@bot.message_handler(commands=['score'])
def command_score(message):
    user_id = message.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
            result = cur.fetchone()
    if result:
        bot.send_message(
            message.chat.id,
            f"У тебя {result[0]} баллов 🟢",
            reply_markup=main_menu_markup(user_id)
        )
    else:
        bot.send_message(message.chat.id, "Ты ещё не зарегистрирован. Напиши /start.")

# Button handlers
@bot.message_handler(func=lambda m: m.text == "📊 Мои баллы")
def button_score(m):
    command_score(m)

@bot.message_handler(func=lambda m: m.text == "✅ Подтвердить участие")
def button_confirm(m):
    bot.send_message(
        m.chat.id,
        "Пожалуйста, отправь свою геолокацию, чтобы подтвердить участие:",
        reply_markup=location_request_markup()
    )

# Admin broadcast flow
broadcast_state = {}

@bot.message_handler(func=lambda m: m.text == "✉️ Рассылка (админ)")
def start_broadcast(m):
    if m.from_user.id != admin_id:
        return bot.send_message(m.chat.id, "❌ У вас нет прав на рассылку.")
    bot.send_message(m.chat.id, "Введите текст для рассылки всем пользователям:")
    broadcast_state[m.chat.id] = 'waiting_for_text'

@bot.message_handler(func=lambda m: broadcast_state.get(m.chat.id) == 'waiting_for_text')
def process_broadcast_text(m):
    text = m.text
    broadcast_state.pop(m.chat.id, None)
    count = 0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            users = cur.fetchall()
    for (uid,) in users:
        try:
            bot.send_message(uid, text)
            count += 1
        except Exception as e:
            logger.error(f"Failed to send to {uid}: {e}")
    bot.send_message(m.chat.id, f"✅ Рассылка завершена. Отправлено: {count}")

# Location handler
@bot.message_handler(content_types=['location'])
def handle_location(message):
    user_id = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    dist = calculate_distance(lat, lon, TARGET_LAT, TARGET_LON)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points, last_checkin FROM users WHERE user_id = %s", (user_id,))
            data = cur.fetchone()
    if not data:
        return bot.send_message(message.chat.id, "Сначала напиши /start для регистрации.")
    points, last_checkin = data
    today = datetime.date.today()
    if last_checkin == today:
        bot.send_message(
            message.chat.id,
            "Ты уже подтвердил участие сегодня 😉",
            reply_markup=main_menu_markup(user_id)
        )
    elif dist <= RADIUS_METERS:
        new_points = points + 20
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET points = %s, last_checkin = %s WHERE user_id = %s",
                    (new_points, today, user_id)
                )
                conn.commit()
        bot.send_message(
            message.chat.id,
            "✅ Участие подтверждено! +20 баллов 🎉",
            reply_markup=main_menu_markup(user_id)
        )
    else:
        bot.send_message(
            message.chat.id,
            "Ты находишься вне зоны мероприятия ❌ Баллы не начислены.",
            reply_markup=main_menu_markup(user_id)
        )

# Start polling
if __name__ == '__main__':
    logger.info("Starting bot polling...")
    bot.infinity_polling(skip_pending=True)
