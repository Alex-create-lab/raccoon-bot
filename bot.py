import asyncio
import logging
import random
import os
import datetime
import sqlite3
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from aiohttp import web

# Загружаем переменные из .env файла
load_dotenv()

# --- НАСТРОЙКИ ---
API_TOKEN = os.getenv('BOT_TOKEN')

if not API_TOKEN:
    raise ValueError("❌ ТОКЕН НЕ НАЙДЕН! Создай файл .env с BOT_TOKEN=твой_токен")

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Создаем бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- ПАПКА ДЛЯ ГИФОК ---
GIF_FOLDER = "/tmp/gifs"  # на Render можно писать в /tmp
os.makedirs(GIF_FOLDER, exist_ok=True)

# --- ТВОИ ГИФКИ С POSTIMAGE ---
GIF_URLS = {
    'happy.gif': 'https://i.postimg.cc/N0VW2Yg5/happy.gif',
    'hungry.gif': 'https://i.postimg.cc/MG4hfxWp/hungry.gif',
    'eat.gif': 'https://i.postimg.cc/25JPLmzk/eat.gif',
    'angry.gif': 'https://i.postimg.cc/CKtWnYFS/angry.gif',
    'sleep.gif': 'https://i.postimg.cc/VNT301Y6/sleep.gif',
    'dance.gif': 'https://i.postimg.cc/XvhTB3VV/dance.gif',
    'sad.gif': 'https://i.postimg.cc/k5ZkR9n5/sad.gif'
}

# --- СКАЧИВАЕМ ГИФКИ ПРИ ЗАПУСКЕ ---
print("🔄 Скачиваю гифки с PostImage...")
for name, url in GIF_URLS.items():
    gif_path = os.path.join(GIF_FOLDER, name)
    try:
        print(f"📥 {name}...", end="")
        r = requests.get(url, timeout=10)
        with open(gif_path, 'wb') as f:
            f.write(r.content)
        print(f" ✅ {len(r.content)} байт")
    except Exception as e:
        print(f" ❌ Ошибка: {e}")

print(f"📁 Гифки сохранены в: {GIF_FOLDER}")

# --- БАЗА ДАННЫХ (SQLite) ---
conn = sqlite3.connect('raccoon_food.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS hunger (
    user_id INTEGER PRIMARY KEY,
    last_feed TEXT,
    hunger_level INTEGER DEFAULT 100,
    streak INTEGER DEFAULT 0,
    last_daily TEXT
)
''')
conn.commit()

# --- ФУНКЦИИ ДЛЯ РАБОТЫ С ГОЛОДОМ ---
def get_hunger(user_id):
    """Получить данные о голоде пользователя"""
    cursor.execute('SELECT last_feed, hunger_level, streak, last_daily FROM hunger WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    
    if result:
        last_feed, hunger_level, streak, last_daily = result
        # Рассчитываем голод (каждый час -5)
        if last_feed:
            last_feed_time = datetime.datetime.fromisoformat(last_feed)
            hours_passed = (datetime.datetime.now() - last_feed_time).total_seconds() / 3600
            hunger_level = max(0, hunger_level - int(hours_passed * 5))
        return last_feed, hunger_level, streak, last_daily
    return None, 100, 0, None

def save_hunger(user_id, hunger_level, streak, last_feed=None, last_daily=None):
    """Сохранить данные"""
    if last_feed is None:
        last_feed = datetime.datetime.now().isoformat()
    
    cursor.execute('''
        INSERT OR REPLACE INTO hunger (user_id, last_feed, hunger_level, streak, last_daily)
        VALUES (?, ?, ?, ?, ?)
    ''', (user_id, last_feed, hunger_level, streak, last_daily))
    conn.commit()

def feed_raccoon(user_id):
    """Покормить енота (+20 к сытости)"""
    _, hunger_level, streak, last_daily = get_hunger(user_id)
    
    # Максимум 100, при кормлении +20
    new_hunger = min(100, hunger_level + 20)
    new_streak = streak + 1
    
    save_hunger(user_id, new_hunger, new_streak)
    return new_hunger, new_streak

def check_daily(user_id):
    """Проверка на ежедневное кормление"""
    _, _, _, last_daily = get_hunger(user_id)
    
    if last_daily:
        last = datetime.datetime.fromisoformat(last_daily)
        now = datetime.datetime.now()
        # Если прошло больше 24 часов
        if (now - last).days >= 1:
            return True, now
        return False, last
    return True, datetime.datetime.now()  # Первый раз

# --- ФУНКЦИЯ ДЛЯ ОТПРАВКИ ГИФОК ---
async def send_raccoon_gif(message: types.Message, gif_name: str, caption: str = ""):
    """Отправляет гифку"""
    gif_path = os.path.join(GIF_FOLDER, gif_name)
    if os.path.exists(gif_path):
        try:
            await message.answer_animation(
                animation=FSInputFile(gif_path),
                caption=caption
            )
        except Exception as e:
            print(f"Ошибка отправки гифки {gif_name}: {e}")
            await message.answer(caption)
    else:
        print(f"❌ Гифка не найдена: {gif_path}")
        await message.answer(caption + "\n(енот здесь, но гифка потерялась)")

# --- ТЕКСТЫ ---
HAPPY_TEXTS = [
    "🍪 Спасибо! Я так счастлив!",
    "🍪 *чавкает* Вкуснота-то какая!",
    "🍪 Ням-ням! Ты лучший!",
    "🍪 Печенька = счастье!",
]

HUNGRY_TEXTS = [
    "🍪 *нюхает воздух* Едой пахнет?",
    "🍪 Кушать хочется... *грустные глаза*",
    "🍪 А дай печеньку? Ну пожалуйста!",
]

ANGRY_TEXTS = [
    "😤 Я ГОЛОДЕН! СРОЧНО ПЕЧЕНЬКУ!",
    "😠 *топает лапкой* Есть хочу!",
    "🤬 КРИТИЧЕСКИЙ УРОВЕНЬ ГОЛОДА!",
]

FULL_TEXTS = [
    "😴 *енот сыт и счастлив* Пойду посплю...",
    "🦝 *гладит животик* Всё, объелся!",
    "😌 Как же хорошо... *засыпает*",
]

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_name = message.from_user.first_name
    
    kb = [
        [types.KeyboardButton(text="🍪 ПОКОРМИТЬ!"), types.KeyboardButton(text="📊 СТАТУС")],
        [types.KeyboardButton(text="🎨 НАРИСУЙ ЕНОТА"), types.KeyboardButton(text="😩 ПОЖАЛОВАТЬСЯ")],
        [types.KeyboardButton(text="📅 ДЕЙЛИК")]
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    
    await send_raccoon_gif(message, "happy.gif", "🦝 *енот вылезает из коробки*")
    await message.answer(
        f"Привет, {user_name}!\n\n"
        f"Я твой домашний енот! Меня нужно:\n"
        f"🍪 Кормить (каждые 3 часа можно)\n"
        f"📅 Кормить раз в день (дейлик)\n"
        f"Если не кормить — я зверею!\n\n"
        f"Жми кнопки! 👇",
        reply_markup=keyboard
    )

@dp.message(lambda message: message.text in ["🍪 ПОКОРМИТЬ!", "/feed"])
async def cmd_feed(message: types.Message):
    user_id = message.from_user.id
    last_feed, hunger_level, streak, _ = get_hunger(user_id)
    
    if last_feed:
        last = datetime.datetime.fromisoformat(last_feed)
        hours_passed = (datetime.datetime.now() - last).total_seconds() / 3600
        if hours_passed < 3:
            wait_time = 3 - hours_passed
            hours = int(wait_time)
            minutes = int((wait_time - hours) * 60)
            await send_raccoon_gif(message, "angry.gif", f"😤 Рано! Подожди {hours}ч {minutes}м!")
            return
    
    new_hunger, new_streak = feed_raccoon(user_id)
    
    if new_hunger >= 100:
        await send_raccoon_gif(message, "sleep.gif", random.choice(FULL_TEXTS))
    elif new_hunger >= 80:
        await send_raccoon_gif(message, "happy.gif", random.choice(HAPPY_TEXTS))
    elif new_hunger >= 50:
        await send_raccoon_gif(message, "eat.gif", "🍪 *хрум-хрум* Спасибо!")
    else:
        await send_raccoon_gif(message, "hungry.gif", random.choice(HUNGRY_TEXTS))
    
    await message.answer(f"📊 Сытость: {new_hunger}% | Дней подряд: {new_streak}")

@dp.message(lambda message: message.text in ["📅 ДЕЙЛИК", "/daily"])
async def cmd_daily(message: types.Message):
    user_id = message.from_user.id
    can_daily, last_time = check_daily(user_id)
    
    if can_daily:
        _, hunger_level, streak, _ = get_hunger(user_id)
        new_hunger = min(100, hunger_level + 50)
        new_streak = streak + 1
        
        save_hunger(user_id, new_hunger, new_streak, last_daily=datetime.datetime.now().isoformat())
        
        await send_raccoon_gif(message, "dance.gif", "🎉 УРА! ЕЖЕДНЕВНАЯ ПЕЧЕНЬКА! 🎉")
        await message.answer(f"🍪 Сытость: {new_hunger}% | Дней подряд: {new_streak}")
    else:
        next_daily = last_time + datetime.timedelta(days=1)
        time_left = next_daily - datetime.datetime.now()
        hours = int(time_left.total_seconds() / 3600)
        minutes = int((time_left.total_seconds() % 3600) / 60)
        
        await send_raccoon_gif(message, "sad.gif", f"😢 Дейлик будет через {hours}ч {minutes}м")

@dp.message(lambda message: message.text in ["📊 СТАТУС", "/status"])
async def cmd_status(message: types.Message):
    user_id = message.from_user.id
    last_feed, hunger_level, streak, last_daily = get_hunger(user_id)
    
    if hunger_level >= 80:
        status = "💚 Сытый и довольный"
        gif = "happy.gif"
    elif hunger_level >= 50:
        status = "💛 Нормальный"
        gif = "hungry.gif"
    elif hunger_level >= 20:
        status = "🧡 Хочет кушать"
        gif = "hungry.gif"
    else:
        status = "❤️‍🔥 СРОЧНО ПОКОРМИ!!!"
        gif = "angry.gif"
    
    text = f"📊 **СТАТУС ЕНОТА**\n\n"
    text += f"🦝 {status}\n"
    text += f"⚡️ Сытость: {hunger_level}%\n"
    text += f"🔥 Дней подряд: {streak}\n"
    
    if last_feed:
        last = datetime.datetime.fromisoformat(last_feed)
        hours = int((datetime.datetime.now() - last).total_seconds() / 3600)
        text += f"⏱ Последний раз ели: {hours}ч назад\n"
    
    await send_raccoon_gif(message, gif, text)

@dp.message(lambda message: message.text in ["😩 ПОЖАЛОВАТЬСЯ", "/poops"])
async def cmd_complain(message: types.Message):
    complaints = [
        "😭 Жизнь боль... Печеньки нет...",
        "😫 Меня никто не любит!",
        "😤 Вчера обещали печеньку, а не дали!",
        "🥺 Холодно в коробке... Нужен плед...",
        "😩 Лапки устали печеньки ждать!"
    ]
    await send_raccoon_gif(message, "sad.gif", random.choice(complaints))

@dp.message(lambda message: message.text in ["🎨 НАРИСУЙ ЕНОТА", "/draw"])
async def cmd_draw(message: types.Message):
    arts = [
        """
    /\\___/\\
   /  ◕‿◕  \\
   \\   w   /
   /  ___  \\
  /  /   \\  \\
  \\_/     \\_/
    """,
        """
      .--.
     /  ."\\
     \\   _/
     /  _\\
    (  _\\
     \\  \\
      \\_\\\\
    """,
        """
    .-.
   (o o)
   | O |
   \\   /
    '~'
    """
    ]
    await message.answer(random.choice(arts))

@dp.message()
async def handle_all(message: types.Message):
    user_id = message.from_user.id
    _, hunger_level, _, _ = get_hunger(user_id)
    
    if hunger_level < 20:
        await send_raccoon_gif(message, "angry.gif", "⚠️ ПОКОРМИ МЕНЯ СРОЧНО! ⚠️")
    elif random.random() < 0.3:
        responses = [
            "🦝 *чешет пузико*",
            "🍪 Печеньку хочешь? А я хочу!",
            "📦 *шуршит в коробке*",
            "👀 *смотрит голодными глазами*",
        ]
        await message.answer(random.choice(responses))

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
async def handle_health(request):
    return web.Response(text="🦝 Енот работает!")

async def run_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    app.router.add_get('/health', handle_health)
    
    port = int(os.getenv('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"🌐 Веб-сервер на порту {port}")

# --- ЗАПУСК ---
async def main():
    await run_web_server()
    print("🚀 Енот-Тамагочи с гифками с PostImage запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())