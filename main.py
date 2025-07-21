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
primary_admin_id = 1747953120  # главный админ

# Database config
db_config = {
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST"),
    'port': os.getenv("DB_PORT"),
}

# Geo settings
TARGET_LAT = float(os.getenv("TARGET_LAT", "41.356015"))
TARGET_LON = float(os.getenv("TARGET_LON", "69.314663"))
RADIUS_METERS = float(os.getenv("RADIUS_METERS", "150"))

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Initialize bot
bot = telebot.TeleBot(token)

# Global state
admin_state = {}
broadcast_history = []  # store broadcasted messages as (chat_id, message_id)

# Database helpers
def get_db_connection():
    return psycopg2.connect(**db_config)

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS admins(user_id BIGINT PRIMARY KEY)"
            )
            cur.execute(
                "INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
                (primary_admin_id,)
            )
            conn.commit()

def is_admin(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admins WHERE user_id=%s", (user_id,))
            return cur.fetchone() is not None

def add_admin(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
                (user_id,)
            )
            conn.commit()

def remove_admin(user_id: int) -> bool:
    if user_id == primary_admin_id:
        return False
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admins WHERE user_id=%s", (user_id,))
            conn.commit()
    return True

def list_admins() -> list:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM admins")
            return [row[0] for row in cur.fetchall()]

def list_users() -> list:
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, name, points FROM users ORDER BY points DESC, name"
            )
            return cur.fetchall()

# Utility: distance calculation
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# Keyboards
def main_menu_markup(user_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Базовые кнопки для всех пользователей
    kb.add("Участие✅", "Баллы📊")

    # Кнопки для админов (без изменения локации)
    if is_admin(user_id):
        kb.add("Текст✉️", "Фото🖼️", "Видео📹")
        kb.add("Файл📎", "Локация📍")
        kb.add("Удалить✂️")
        # Только главный админ может менять локацию и просматривать пользователей
        if user_id == primary_admin_id:
            kb.add("Изменить📌")
            kb.add("Пользователи👥")
            kb.add("Назначить👑", "Снять👑")

    return kb

def location_request_markup():
    kb = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    kb.add(types.KeyboardButton(text="📍 Отправить", request_location=True))
    return kb

# Handlers
@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    name = m.from_user.first_name or m.from_user.username
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(user_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (uid, name)
            )
            conn.commit()
    text = f"Привет, {name}! Добро пожаловать в YES PLUS."
    bot.send_message(m.chat.id, text, reply_markup=main_menu_markup(uid))

@bot.message_handler(func=lambda m: m.text == "Баллы📊")
def cmd_score(m):
    uid = m.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            res = cur.fetchone()
    text = f"У тебя {res[0]} баллов." if res else "Запишись через Участие✅"
    bot.send_message(m.chat.id, text, reply_markup=main_menu_markup(uid))

@bot.message_handler(func=lambda m: m.text == "Участие✅")
def cmd_confirm(m):
