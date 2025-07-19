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
primary_admin_id = int(os.getenv("ADMIN_ID", "0"))  # initial admin from .env

db_config = {
    'dbname': os.getenv("DB_NAME"),
    'user': os.getenv("DB_USER"),
    'password': os.getenv("DB_PASSWORD"),
    'host': os.getenv("DB_HOST"),
    'port': os.getenv("DB_PORT"),
}

# Geo target settings (default)
TARGET_LAT = float(os.getenv("TARGET_LAT", "41.356015"))
TARGET_LON = float(os.getenv("TARGET_LON", "69.314663"))
RADIUS_METERS = float(os.getenv("RADIUS_METERS", "150"))

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()

# Initialize bot
bot = telebot.TeleBot(token)

# Helper: DB connection
def get_db_connection():
    conn = psycopg2.connect(**db_config)
    return conn

# Setup DB tables if not exists
def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # users table assumed exists
            # create admins table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS admins (
                  user_id BIGINT PRIMARY KEY
                )""")
            # ensure primary admin in admins
            cur.execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (primary_admin_id,))
            conn.commit()

# Check admin status
def is_admin(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admins WHERE user_id = %s", (user_id,))
            return cur.fetchone() is not None

# Distance calculation
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# Keyboards
def main_menu_markup(user_id: int):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("✅ Подтвердить участие", "📊 Мои баллы")
    if is_admin(user_id):
        markup.add(
            "✉️ Текст всем", "🖼️ Фото всем", "📹 Видео всем",
            "📎 Файл всем", "📍 Локация всем", "⚙️ Изменить локацию",
            "👑 Назначить админа"
        )
    return markup

def location_request_markup():
    kb = types.ReplyKeyboardMarkup(one_time_keyboard=True, resize_keyboard=True)
    kb.add(types.KeyboardButton(text="📍 Отправить геолокацию", request_location=True))
    return kb

# State for admin flows
admin_state = {}

# /start handler
@bot.message_handler(commands=['start'])
def command_start(msg):
    uid = msg.from_user.id
    name = msg.from_user.first_name or msg.from_user.username
    # register user
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, name) VALUES (%s,%s) ON CONFLICT DO NOTHING", (uid, name))
            conn.commit()
    bot.send_message(
        msg.chat.id,
        f"Привет, {name}! Добро пожаловать в YES PLUS 🎉\n20 баллов за участие в тимбилдинге.",
        reply_markup=main_menu_markup(uid)
    )

# /score handler
@bot.message_handler(commands=['score'])
def command_score(msg):
    uid = msg.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id=%s", (uid,))
            res = cur.fetchone()
    if res:
        bot.send_message(msg.chat.id, f"У тебя {res[0]} баллов 🟢", reply_markup=main_menu_markup(uid))
    else:
        bot.send_message(msg.chat.id, "Ты ещё не зарегистрирован. Напиши /start.")

# Participation confirmation
@bot.message_handler(func=lambda m: m.text == "✅ Подтвердить участие")
def btn_confirm(m):
    bot.send_message(m.chat.id, "Пожалуйста, отправь свою геолокацию:", reply_markup=location_request_markup())

# Score button
@bot.message_handler(func=lambda m: m.text == "📊 Мои баллы")
def btn_score(m):
    command_score(m)

# Admin flows: text, photo, video, file, location, change event loc, assign admin
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "✉️ Текст всем")
def admin_text_all(m):
    admin_state[m.chat.id] = {'action':'text','step':1}
    bot.send_message(m.chat.id, "Введите текст для рассылки:")

@bot.message_handler(func=lambda m: admin_state.get(m.chat.id,{}).get('action')=='text')
def process_admin_text(m):
    state = admin_state[m.chat.id]
    text = m.text
    cnt=0
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            users = cur.fetchall()
    for (uid,) in users:
        try:
            bot.send_message(uid, text)
            cnt+=1
        except:
            pass
    bot.send_message(m.chat.id, f"Рассылка текста завершена: {cnt}")
    admin_state.pop(m.chat.id)

# Generic media broadcast helper
def broadcast_media(media_type, send_func):
    def decorator(m):
        admin_state[m.chat.id] = {'action':media_type,'step':1}
        bot.send_message(m.chat.id, f"Пришлите {media_type} или ссылку:")
    return decorator

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "🖼️ Фото всем")
def admin_photo_all(m):
    admin_state[m.chat.id] = {'action':'photo','step':1}
    bot.send_message(m.chat.id, "Пришлите фото или URL:")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📹 Видео всем")
def admin_video_all(m):
    admin_state[m.chat.id] = {'action':'video','step':1}
    bot.send_message(m.chat.id, "Пришлите видео или URL:")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📎 Файл всем")
def admin_file_all(m):
    admin_state[m.chat.id] = {'action':'file','step':1}
    bot.send_message(m.chat.id, "Пришлите файл или ссылку:")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📍 Локация всем")
def admin_location_all(m):
    admin_state[m.chat.id] = {'action':'loc','step':1}
    bot.send_message(m.chat.id, "Отправьте локацию для рассылки:", reply_markup=location_request_markup())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "⚙️ Изменить локацию")
def admin_set_event_loc(m):
    admin_state[m.chat.id] = {'action':'setloc','step':1}
    bot.send_message(m.chat.id, "Введите новые координаты и радиус: lat lon radius")

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "👑 Назначить админа")
def admin_assign(m):
    admin_state[m.chat.id] = {'action':'assign','step':1}
    bot.send_message(m.chat.id, "Введите Telegram user_id нового админа:")

# Process admin_state for media, location, setloc, assign
@bot.message_handler(content_types=['text','photo','document','video','location'])
def admin_state_handler(m):
    state = admin_state.get(m.chat.id)
    if not state: return
    action = state['action']
    # Text handled separately
    if action == 'photo':
        if state['step']==1:
            if m.photo:
                state['file_id']=m.photo[-1].file_id
            else:
                state['file_url']=m.text
            state['step']=2
            bot.send_message(m.chat.id, "Введите подпись или 'нет':")
        else:
            caption=None if m.text.lower()=='нет' else m.text
            cnt=0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users=cur.fetchall()
            for (uid,) in users:
                try:
                    if 'file_id' in state:
                        bot.send_photo(uid, state['file_id'], caption=caption)
                    else:
                        bot.send_photo(uid, state['file_url'], caption=caption)
                    cnt+=1
                except: pass
            bot.send_message(m.chat.id,f"Фото разослано: {cnt}")
            admin_state.pop(m.chat.id)
    elif action=='video':
        if state['step']==1:
            if m.video:
                state['file_id']=m.video.file_id
            else:
                state['file_url']=m.text
            state['step']=2
            bot.send_message(m.chat.id,"Введите подпись или 'нет':")
        else:
            caption=None if m.text.lower()=='нет' else m.text
            cnt=0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users=cur.fetchall()
            for (uid,) in users:
                try:
                    if 'file_id' in state:
                        bot.send_video(uid, state['file_id'], caption=caption)
                    else:
                        bot.send_video(uid, state['file_url'], caption=caption)
                    cnt+=1
                except: pass
            bot.send_message(m.chat.id,f"Видео разослано: {cnt}")
            admin_state.pop(m.chat.id)
    elif action=='file':
        if state['step']==1:
            if m.document:
                state['file_id']=m.document.file_id
            else:
                state['file_url']=m.text
            state['step']=2
            bot.send_message(m.chat.id,"Введите подпись или 'нет':")
        else:
            caption=None if m.text.lower()=='нет' else m.text
            cnt=0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users=cur.fetchall()
            for (uid,) in users:
                try:
                    if 'file_id' in state:
                        bot.send_document(uid, state['file_id'], caption=caption)
                    else:
                        bot.send_document(uid, state['file_url'], caption=caption)
                    cnt+=1
                except: pass
            bot.send_message(m.chat.id,f"Файл разослан: {cnt}")
            admin_state.pop(m.chat.id)
    elif action=='loc':
        if m.content_type=='location':
            lat,lon=m.location.latitude,m.location.longitude
            cnt=0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users=cur.fetchall()
            for (uid,) in users:
                try:
                    bot.send_location(uid, lat, lon)
                    cnt+=1
                except: pass
            bot.send_message(m.chat.id,f"Локация разослана: {cnt}")
            admin_state.pop(m.chat.id)
    elif action=='setloc':
        parts=m.text.split()
        try:
            lat,lon,r=map(float,parts)
            global TARGET_LAT,TARGET_LON,RADIUS_METERS
            TARGET_LAT, TARGET_LON, RADIUS_METERS = lat, lon, r
            bot.send_message(m.chat.id,f"Локация события обновлена: {lat},{lon} Р={r}м")
        except:
            bot.send_message(m.chat.id,"Ошибка формата. lat lon radius")
        admin_state.pop(m.chat.id)
    elif action=='assign':
        try:
            new_admin=int(m.text)
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (new_admin,))
                    conn.commit()
            bot.send_message(m.chat.id,f"Пользователь {new_admin} назначен админом.")
        except:
            bot.send_message(m.chat.id,"Введите корректный user_id")
        admin_state.pop(m.chat.id)

# Participant location handler for check-in
def participant_location_checkin(m):
    uid=m.from_user.id
    lat,lon=m.location.latitude,m.location.longitude
    dist=calculate_distance(lat,lon,TARGET_LAT,TARGET_LON)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points,last_checkin FROM users WHERE user_id=%s",(uid,))
            data=cur.fetchone()
    if not data:
        return bot.send_message(m.chat.id,"Сначала /start")
    pts,last=data
    today=datetime.date.today()
    if last==today:
        bot.send_message(m.chat.id,"Уже сегодня подтвердили.",reply_markup=main_menu_markup(uid))
    elif dist<=RADIUS_METERS:
        new=pts+20
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET points=%s,last_checkin=%s WHERE user_id=%s",(new,today,uid))
                conn.commit()
        bot.send_message(m.chat.id,"✅ Участие подтверждено!", reply_markup=main_menu_markup(uid))
    else:
        bot.send_message(m.chat.id,"Вы вне зоны.", reply_markup=main_menu_markup(uid))

@bot.message_handler(content_types=['location'])
def handle_location(m):
    # Admin-state handled above
    if is_admin(m.from_user.id) and admin_state.get(m.chat.id):
        return
    participant_location_checkin(m)

# Initialize and start
if __name__ == '__main__':
    init_db()
    logger.info("Bot polling started")
    bot.infinity_polling(skip_pending=True)
