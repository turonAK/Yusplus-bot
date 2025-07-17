import telebot
from telebot import types
from math import radians, cos, sin, asin, sqrt
from dotenv import load_dotenv
import os
import datetime

load_dotenv()  # Загружаем переменные из .env

TOKEN = os.getenv("BOT_TOKEN")

# === ТВОЙ ТОКЕН ОТ BOTFATHE ===
bot = telebot.TeleBot(TOKEN)

# === КООРДИНАТЫ МЕСТА ТИМБИЛДИНГА ===
TARGET_LAT = 41.356015
TARGET_LON = 69.314663
RADIUS_METERS = 150  # радиус допустимого отклонения

# === ПРОСТАЯ БАЗА ДАННЫХ
users = {}

# === ПОДСЧЁТ РАССТОЯНИЯ
def calculate_distance(lat1, lon1, lat2, lon2):
    # Haversine formula
    R = 6371000  # Земной радиус в метрах
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# === /start
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    if user_id not in users:
        users[user_id] = {"name": message.from_user.first_name, "points": 0, "last_checkin": None}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Подтвердить участие", "📊 Мои баллы")
    bot.send_message(message.chat.id, f"Привет, {message.from_user.first_name}! Добро пожаловать в YES+ 🎉\nТы получаешь 20 баллов за каждое участие в тимбилдинге.\nНажми 'Подтвердить участие', когда будешь на месте!", reply_markup=markup)

# === /score
@bot.message_handler(commands=['score'])
def score(message):
    user_id = message.from_user.id
    if user_id in users:
        points = users[user_id]["points"]
        bot.send_message(message.chat.id, f"У тебя {points} баллов 🟢")
    else:
        bot.send_message(message.chat.id, "Ты ещё не зарегистрирован. Напиши /start.")

# === Проверка текста кнопок
@bot.message_handler(func=lambda m: m.text == "📊 Мои баллы")
def handle_score_button(message):
    score(message)

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
    if user_id not in users:
        bot.send_message(message.chat.id, "Сначала напиши /start для регистрации.")
        return

    lat = message.location.latitude
    lon = message.location.longitude
    distance = calculate_distance(lat, lon, TARGET_LAT, TARGET_LON)

    today = datetime.date.today()
    last_check = users[user_id]["last_checkin"]

    if last_check == today:
        bot.send_message(message.chat.id, "Ты уже подтвердил участие сегодня 😉")
        return

    if distance <= RADIUS_METERS:
        users[user_id]["points"] += 20
        users[user_id]["last_checkin"] = today
        bot.send_message(message.chat.id, "✅ Участие подтверждено! +20 баллов 🎉")
    else:
        bot.send_message(message.chat.id, "Ты находишься вне зоны мероприятия ❌\nБаллы не начислены.")

# === Запуск бота
bot.polling()
