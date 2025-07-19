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
broadcast_history = []  # store {(chat_id, message_id)}

# Database helpers

def get_db_connection():
    return psycopg2.connect(**db_config)

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS admins(user_id BIGINT PRIMARY KEY)")
            cur.execute("INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (primary_admin_id,))
            conn.commit()

def is_admin(user_id: int) -> bool:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM admins WHERE user_id=%s", (user_id,))
            return cur.fetchone() is not None

def add_admin(user_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO admins(user_id) VALUES(%s) ON CONFLICT DO NOTHING", (user_id,))
            conn.commit()

def remove_admin(user_id: int):
    if user_id == primary_admin_id: return False
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

# Utility: distance
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1))*cos(radians(lat2))*sin(dlon/2)**2
    return R*2*asin(sqrt(a))

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
    uid=m.from_user.id; name=m.from_user.first_name or m.from_user.username
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users(user_id,name) VALUES(%s,%s) ON CONFLICT DO NOTHING",(uid,name));conn.commit()
    m_text=f"Привет, {name}! Добро пожаловать в YES PLUS."
    bot.send_message(m.chat.id, m_text, reply_markup=main_menu_markup(uid))

@bot.message_handler(func=lambda m:m.text=="Баллы📊")
def cmd_score(m):
    uid=m.from_user.id
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points FROM users WHERE user_id=%s",(uid,));res=cur.fetchone()
    txt=f"У тебя {res[0]} баллов." if res else "Запишись через Участие✅"
    bot.send_message(m.chat.id, txt, reply_markup=main_menu_markup(uid))

@bot.message_handler(func=lambda m:m.text=="Участие✅")
def cmd_confirm(m):
    bot.send_message(m.chat.id, "Отправь геолокацию:", reply_markup=location_request_markup())

@bot.message_handler(content_types=['location'])
def handle_loc(m):
    uid=m.from_user.id
    if is_admin(uid) and admin_state.get(m.chat.id): return admin_state_handler(m)
    lat,lon=m.location.latitude,m.location.longitude; dist=calculate_distance(lat,lon,TARGET_LAT,TARGET_LON)
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT points,last_checkin FROM users WHERE user_id=%s",(uid,));d=cur.fetchone()
    if not d: return bot.send_message(m.chat.id,"Сначала Участие✅")
    pts,last=d; today=datetime.date.today()
    if last==today: txt="Сегодня уже учтено."
    elif dist<=RADIUS_METERS: cur=conn.cursor();new=pts+20;cur.execute("UPDATE users SET points=%s,last_checkin=%s WHERE user_id=%s",(new,today,uid));conn.commit();txt="Участие подтверждено!"
    else: txt="Вне зоны мероприятия."
    bot.send_message(m.chat.id, txt, reply_markup=main_menu_markup(uid))

# Admin commands: text, photo, video, file, location, change, delete msgs, assign, remove
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text in ["Текст✉️","Фото🖼️","Видео📹","Файл📎","Локация📍","Изменить📌","Удалить✂️","Назначить👑","Снять👑"])
def admin_cmd(m):
    action_map={
        "Текст✉️":"text","Фото🖼️":"photo","Видео📹":"video","Файл📎":"file",
        "Локация📍":"loc","Изменить📌":"setloc","Удалить✂️":"clear","Назначить👑":"assign","Снять👑":"remove_admin"
    }
    cmd=action_map[m.text]
    admin_state[m.chat.id]={'action':cmd,'step':1,'data':{}}
    prompts={
        'text':'Введи текст для рассылки:',
        'photo':'Пришли фото или URL:',
        'video':'Пришли видео или URL:',
        'file':'Пришли файл или URL:',
        'loc':'Отправь локацию для рассылки:',
        'setloc':'Новые координаты: lat lon radius',
        'clear':'Сколько последних итераций удалить?',
        'assign':'User_id нового админа:',
        'remove_admin':'Список админов:\n'+"\n".join(str(a) for a in list_admins())+"\nВведи ID для удаления:"
    }
    bot.send_message(m.chat.id, prompts[cmd])

@bot.message_handler(content_types=['text','photo','video','document','location'])
def admin_state_handler(m):
    state=admin_state.get(m.chat.id)
    if not state: return
    a=state['action']; step=state['step']
    # Broadcast text
    if a=='text':
        if step==1:
            state['data']['text']=m.text; state['step']=2; return bot.send_message(m.chat.id,'Рассылка? да/нет')
        if m.text.lower()=='да': cnt=0; text=state['data']['text']
        for (uid,) in get_db_connection().cursor().execute("SELECT user_id FROM users"):
            try: msg=bot.send_message(uid,text); broadcast_history.append((uid,msg.message_id)); cnt+=1
            except: pass
        bot.send_message(m.chat.id,f"Отправлено {cnt}")
        admin_state.pop(m.chat.id)
    # Clear broadcast messages
    elif a=='clear':
        if step==1:
            try: n=int(m.text); state['step']=2; state['data']['n']=n; return bot.send_message(m.chat.id,'Подтвердить удаление? да/нет')
            except: return bot.send_message(m.chat.id,'Число?')
        if m.text.lower()=='да': cnt=0
            for uid,msg_id in broadcast_history[-state['data']['n']:]:
                try: bot.delete_message(uid,msg_id); cnt+=1
                except: pass
            bot.send_message(m.chat.id,f"Удалено {cnt}")
        admin_state.pop(m.chat.id)
    # Assign admin
    elif a=='assign' and step==1:
        try: add_admin(int(m.text)); bot.send_message(m.chat.id,'Добавлен');
        except: bot.send_message(m.chat.id,'Ошибка'); admin_state.pop(m.chat.id)
    # Remove admin
    elif a=='remove_admin' and step==1:
        try: uid=int(m.text)
            if remove_admin(uid): bot.send_message(m.chat.id,'Удалён')
            else: bot.send_message(m.chat.id,'Нельзя удалить главного')
        except: bot.send_message(m.chat.id,'Ошибка')
        admin_state.pop(m.chat.id)
    # Other media and loc and setloc omitted for brevity...

# Init and start
if __name__=='__main__':
    init_db(); logger.info('Bot started'); bot.infinity_polling()
