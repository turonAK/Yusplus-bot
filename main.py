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
broadcast_history = []  # store tuples of (chat_id, message_id)

# Database helpers

def get_db_connection():
    return psycopg2.connect(**db_config)

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS admins(user_id BIGINT PRIMARY KEY)")
            cur.execute(
                "INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (primary_admin_id,)
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
                "INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (user_id,)
            )
            conn.commit()

def remove_admin(user_id: int):
    if user_id == primary_admin_id:
        return False
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM admins WHERE user_id=%s", (user_id,))
            conn.commit()
    return True

def list_admins():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM admins")
            return [row[0] for row in cur.fetchall()]

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
    kb.add("Участие✅", "Баллы📊")
    if is_admin(user_id):
        kb.add("Текст✉️", "Фото🖼️", "Видео📹")
        kb.add("Файл📎", "Локация📍")
        kb.add("Изменить📌", "Удалить✂️")
        if user_id == primary_admin_id:
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
    bot.send_message(m.chat.id, "Отправь геолокацию:", reply_markup=location_request_markup())

@bot.message_handler(content_types=['location'])
def handle_loc(m):
    uid = m.from_user.id
    # Admin flow
    if is_admin(uid) and admin_state.get(uid):
        return admin_state_handler(m)
    # Participant flow
    lat, lon = m.location.latitude, m.location.longitude
    dist = calculate_distance(lat, lon, TARGET_LAT, TARGET_LON)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT points, last_checkin FROM users WHERE user_id=%s",
                (uid,)
            )
            data = cur.fetchone()
    if not data:
        return bot.send_message(m.chat.id, "Сначала нажми Участие✅")
    pts, last = data
    today = datetime.date.today()
    if last == today:
        reply = "Сегодня уже учтено."
    elif dist <= RADIUS_METERS:
        new_pts = pts + 20
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET points=%s, last_checkin=%s WHERE user_id=%s",
                    (new_pts, today, uid)
                )
                conn.commit()
        reply = "Участие подтверждено!"
    else:
        reply = "Вне зоны мероприятия."
    bot.send_message(m.chat.id, reply, reply_markup=main_menu_markup(uid))

# Admin commands trigger
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in [
    "Текст✉️", "Фото🖼️", "Видео📹", "Файл📎", "Локация📍", "Изменить📌", "Удалить✂️",
    "Назначить👑", "Снять👑"
])
def admin_cmd(m):
    action_map = {
        "Текст✉️": "text", "Фото🖼️": "photo", "Видео📹": "video", "Файл📎": "file",
        "Локация📍": "loc", "Изменить📌": "setloc", "Удалить✂️": "clear",
        "Назначить👑": "assign", "Снять👑": "remove_admin"
    }
    cmd = action_map[m.text]
    admin_state[m.from_user.id] = {'action': cmd, 'step': 1, 'data': {}}
    prompts = {
        'text': 'Введи текст для рассылки:',
        'photo': 'Пришли фото или URL:',
        'video': 'Пришли видео или URL:',
        'file': 'Пришли файл или URL:',
        'loc': 'Отправь локацию для рассылки:',
        'setloc': 'Новые координаты: lat lon radius',
        'clear': 'Сколько последних сообщений удалить?',
        'assign': 'User_id нового админа:',
        'remove_admin': 'Текущие админы:\n' + "\n".join(str(a) for a in list_admins()) + "\nВведи ID для удаления:" 
    }
    bot.send_message(m.chat.id, prompts[cmd])

@bot.message_handler(content_types=['text', 'photo', 'video', 'document', 'location'])
def admin_state_handler(m):
    state = admin_state.get(m.from_user.id)
    if not state:
        return
    action = state['action']
    # TEXT broadcast
    if action == 'text':
        if state['step'] == 1:
            state['data']['text'] = m.text
            state['step'] = 2
            bot.send_message(m.chat.id, 'Подтвердить рассылку? да/нет')
        else:
            if m.text.lower() == 'да':
                cnt = 0
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT user_id FROM users")
                        users = cur.fetchall()
                for (uid,) in users:
                    try:
                        msg = bot.send_message(uid, state['data']['text'])
                        broadcast_history.append((uid, msg.message_id))
                        cnt += 1
                    except:
                        pass
                bot.send_message(m.chat.id, f"Рассылка завершена: {cnt}")
            else:
                bot.send_message(m.chat.id, 'Рассылка отменена')
            admin_state.pop(m.from_user.id)
    # CLEAR messages
    elif action == 'clear':
        if state['step'] == 1:
            try:
                n = int(m.text)
                state['data']['n'] = n
                state['step'] = 2
                bot.send_message(m.chat.id, 'Подтвердить удаление? да/нет')
            except:
                bot.send_message(m.chat.id, 'Укажи число')
        else:
            if m.text.lower() == 'да':
                cnt = 0
                to_delete = broadcast_history[-state['data']['n']:]
                for uid, mid in to_delete:
                    try:
                        bot.delete_message(uid, mid)
                        cnt += 1
                    except:
                        pass
                bot.send_message(m.chat.id, f"Удалено: {cnt}")
            else:
                bot.send_message(m.chat.id, 'Удаление отменено')
            admin_state.pop(m.from_user.id)
    # ASSIGN admin
    elif action == 'assign':
        try:
            new_id = int(m.text)
            add_admin(new_id)
            bot.send_message(m.chat.id, f"Пользователь {new_id} добавлен админом")
        except:
            bot.send_message(m.chat.id, 'Ошибка ID')
        admin_state.pop(m.from_user.id)
    # REMOVE admin
    elif action == 'remove_admin':
        try:
            rem_id = int(m.text)
            if remove_admin(rem_id):
                bot.send_message(m.chat.id, f"Админ {rem_id} удалён")
            else:
                bot.send_message(m.chat.id, 'Нельзя удалить главного админа')
        except:
            bot.send_message(m.chat.id, 'Ошибка ID')
        admin_state.pop(m.from_user.id)
    # LOC broadcast
    elif action == 'loc' and m.content_type == 'location':
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
    # SETLOC
    elif action == 'setloc':
        try:
            lat, lon, r = map(float, m.text.split())
            TARGET_LAT, TARGET_LON, RADIUS_METERS = lat, lon, r
            bot.send_message(m.chat.id, f"Новая локация: {lat}, {lon}, радиус {r}м")
        except:
            bot.send_message(m.chat.id, 'Неверный формат')
        admin_state.pop(m.from_user.id)
    # PHOTO, VIDEO, FILE can be implemented similarly if needed

# Init and start
if __name__ == '__main__':
    init_db()
    logger.info('Bot started')
    bot.infinity_polling()
