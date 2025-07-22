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
user_state = {}          # store registration state

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
            cur.execute(
                "CREATE TABLE IF NOT EXISTS users("
                "user_id BIGINT PRIMARY KEY,"
                "name TEXT,"
                "points INT DEFAULT 0,"
                "last_checkin DATE"
                ")"
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
    kb.add("Участие✅", "Баллы📊")
    if is_admin(user_id):
        kb.add("Текст✉️", "Фото🖼️", "Видео📹")
        kb.add("Файл📎", "Локация📍")
        kb.add("Удалить✂️")
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
    user_state[uid] = {'action': 'register'}
    bot.send_message(
        m.chat.id,
        "Добро пожаловать в YES PLUS! Пожалуйста, введите ваше имя и фамилию, чтобы зарегистрироваться:"
    )

@bot.message_handler(func=lambda m: m.from_user.id in user_state and user_state[m.from_user.id]['action'] == 'register', content_types=['text'])
def handle_registration(m):
    uid = m.from_user.id
    full_name = m.text.strip()
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users(user_id, name) VALUES(%s,%s) "
                "ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name",
                (uid, full_name)
            )
            conn.commit()
    user_state.pop(uid, None)
    bot.send_message(m.chat.id, f"Спасибо, {full_name}! Теперь вы зарегистрированы.", reply_markup=main_menu_markup(uid))

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

@bot.message_handler(func=lambda m: m.text == "Пользователи👥" and m.from_user.id == primary_admin_id)
def cmd_list_users(m):
    users = list_users()
    if not users:
        bot.send_message(m.chat.id, "Пользователи отсутствуют.")
        return
    lines = [f"{u['name']} ({u['user_id']}): {u['points']} баллов" for u in users]
    text = "\n".join(lines)
    for chunk in [text[i:i+3500] for i in range(0, len(text), 3500)]:
        bot.send_message(m.chat.id, chunk)

@bot.message_handler(content_types=['location'])
def handle_location(m):
    uid = m.from_user.id
    if is_admin(uid) and uid in admin_state:
        return admin_state_handler(m)
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
        bot.send_message(m.chat.id, "Сначала нажми Участие✅")
        return
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

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in [
    "Текст✉️", "Фото🖼️", "Видео📹", "Файл📎", "Локация📍", "Изменить📌", "Удалить✂️", "Назначить👑", "Снять👑"
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
    step = state['step']
    data = state['data']

    if action == 'text':
        if step == 1:
            data['text'] = m.text
            state['step'] = 2
            bot.send_message(m.chat.id, 'Подтвердить рассылку? да/нет')
            return
        if m.text.lower() == 'да':
            cnt = 0
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT user_id FROM users")
                    users = cur.fetchall()
            for (uid,) in users:
                try:
                    msg = bot.send_message(uid, data['text'])
                    broadcast_history.append((uid, msg.message_id))
                    cnt += 1
                except:
                    pass
            bot.send_message(m.chat.id, f"Рассылка завершена: {cnt}")
        else:
            bot.send_message(m.chat.id, 'Рассылка отменена')
        admin_state.pop(m.from_user.id)
        return

    if action == 'photo':
        if step == 1:
            if m.photo:
                data['file_id'] = m.photo[-1].file_id
            else:
                data['file_url'] = m.text
            state['step'] = 2
            bot.send_message(m.chat.id, 'Введите подпись или "нет"')
            return
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'file_id' in data:
                    msg = bot.send_photo(uid, data['file_id'], caption=caption)
                else:
                    msg = bot.send_photo(uid, data['file_url'], caption=caption)
                broadcast_history.append((uid, msg.message_id))
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Фото разослано: {cnt}")
        admin_state.pop(m.from_user.id)
        return

    if action == 'video':
        if step == 1:
            if m.video:
                data['file_id'] = m.video.file_id
            else:
                data['file_url'] = m.text
            state['step'] = 2
            bot.send_message(m.chat.id, 'Введите подпись или "нет"')
            return
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'file_id' in data:
                    msg = bot.send_video(uid, data['file_id'], caption=caption)
                else:
                    msg = bot.send_video(uid, data['file_url'], caption=caption)
                broadcast_history.append((uid, msg.message_id))
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Видео разослано: {cnt}")
        admin_state.pop(m.from_user.id)
        return

    if action == 'file':
        if step == 1:
            if m.document:
                data['file_id'] = m.document.file_id
            else:
                data['file_url'] = m.text
            state['step'] = 2
            bot.send_message(m.chat.id, 'Введите подпись или "нет"')
            return
        caption = None if m.text.lower() == 'нет' else m.text
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                if 'file_id' in data:
                    msg = bot.send_document(uid, data['file_id'], caption=caption)
                else:
                    msg = bot.send_document(uid, data['file_url'], caption=caption)
                broadcast_history.append((uid, msg.message_id))
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Файл разослан: {cnt}")
        admin_state.pop(m.from_user.id)
        return

    if action == 'loc' and m.content_type == 'location':
        lat, lon = m.location.latitude, m.location.longitude
        cnt = 0
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT user_id FROM users")
                users = cur.fetchall()
        for (uid,) in users:
            try:
                msg = bot.send_location(uid, lat, lon)
                broadcast_history.append((uid, msg.message_id))
                cnt += 1
            except:
                pass
        bot.send_message(m.chat.id, f"Локация разослана: {cnt}")
        admin_state.pop(m.from_user.id)
        return

    if action == 'setloc':
        try:
            lat, lon, r = map(float, m.text.split())
            global TARGET_LAT, TARGET_LON, RADIUS_METERS
            TARGET_LAT, TARGET_LON, RADIUS_METERS = lat, lon, r
            bot.send_message(m.chat.id, f"Новая локация: {lat}, {lon}, радиус {r}м")
        except:
            bot.send_message(m.chat.id, 'Неверный формат')
        admin_state.pop(m.from_user.id)
        return

    if action == 'clear':
        if step == 1:
            try:
                n = int(m.text)
                data['n'] = n
                state['step'] = 2
                bot.send_message(m.chat.id, 'Подтвердить удаление? да/нет')
                return
            except:
                bot.send_message(m.chat.id, 'Укажи число')
                return
        if m.text.lower() == 'да':
            cnt = 0
            to_delete = broadcast_history[-data['n']:]
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
        return

    if action == 'assign':
        try:
            new_id = int(m.text)
            add_admin(new_id)
            bot.send_message(m.chat.id, f"Админ {new_id} добавлен")
        except:
            bot.send_message(m.chat.id, 'Ошибка ID')
        admin_state.pop(m.from_user.id)
        return

    if action == 'remove_admin':
        try:
            rem_id = int(m.text)
            if remove_admin(rem_id):
                bot.send_message(m.chat.id, f"Админ {rem_id} удалён")
            else:
                bot.send_message(m.chat.id, 'Нельзя удалить главного')
        except:
            bot.send_message(m.chat.id, 'Ошибка ID')
        admin_state.pop(m.from_user.id)
        return

if __name__ == '__main__':
    init_db()
    logger.info('Bot started')
    bot.infinity_polling()
