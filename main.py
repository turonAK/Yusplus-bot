import telebot
from telebot import types
from math import radians, cos, sin, asin, sqrt
from dotenv import load_dotenv
import os
import datetime
import psycopg2

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(TOKEN)

# === Геопозиция мероприятия ===
TARGET_LAT = 41.356015
TARGET_LON = 69.314663
RADIUS_METERS = 150

# === Подключение к PostgreSQL ===
conn = psycopg2.connect(
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT")
)
cursor = conn.cursor()

# === Расчёт расстояния
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Радиус Земли в метрах
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# === /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name

    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    if cursor.fetchone() is None:
        cursor.execute("INSERT INTO users (user_id, name) VALUES (%s, %s)", (user_id, name))
        conn.commit()

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Подтвердить участие", "📊 Мои баллы")
    bot.send_message(
        message.chat.id,
        f"Привет, {name}! Добро пожаловать в YES+ 🎉\nТы получаешь 20 баллов за каждое участие в тимбилдинге.\nНажми 'Подтвердить участие', когда будешь на месте!",
        reply_markup=markup
    )

# === /score
@bot.message_handler(commands=['score'])
def score(message):
    user_id = message.from_user.id
    cursor.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    if result:
        bot.send_message(message.chat.id, f"У тебя {result[0]} баллов 🟢")
    else:
        bot.send_message(message.chat.id, "Ты ещё не зарегистрирован. Напиши /start.")

# === Кнопка "Мои баллы"
@bot.message_handler(func=lambda m: m.text == "📊 Мои баллы")
def handle_score_button(message):
    score(message)

# === Кнопка "Подтвердить участие"
@bot.message_handler(func=lambda m: m.text == "✅ Подтвердить участие")
def ask_location(message):
    keyboard = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    button_geo = types.KeyboardButton(text="📍 Отправить геолокацию", request_location=True)
    keyboard.add(button_geo)
    bot.send_message(message.chat.id, "Пожалуйста, отправь свою геолокацию, чтобы подтвердить участие:", reply_markup=keyboard)

# === Обработка геолокации
@bot.message_handler(content_types=['location'])
def handle_location(message):
    user_id = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude
    distance = calculate_distance(lat, lon, TARGET_LAT, TARGET_LON)

    cursor.execute("SELECT points, last_checkin FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()

    if not result:
        bot.send_message(message.chat.id, "Сначала напиши /start для регистрации.")
        return

    points, last_checkin = result
    today = datetime.date.today()

    if last_checkin == today:
        bot.send_message(message.chat.id, "Ты уже подтвердил участие сегодня 😉")
        return

    if distance <= RADIUS_METERS:
        new_points = points + 20
        cursor.execute("UPDATE users SET points = %s, last_checkin = %s WHERE user_id = %s", (new_points, today, user_id))
        conn.commit()
        bot.send_message(message.chat.id, "✅ Участие подтверждено! +20 баллов 🎉")
    else:
        bot.send_message(message.chat.id, "Ты находишься вне зоны мероприятия ❌\nБаллы не начислены.")

# === Запуск бота
bot.polling()
