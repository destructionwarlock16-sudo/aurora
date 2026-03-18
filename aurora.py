import os
import asyncio
import sqlite3
import random
import glob
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from openai import AsyncOpenAI

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROK_API_KEY   = os.getenv("GROK_API_KEY")
FANVUE_LINK    = "https://www.fanvue.com/aurora-valencia"
ADMIN_ID       = 8548080791  # your Telegram user ID

MAX_IMAGES_PER_DAY = 4

GITHUB_USERNAME = "destructionwarlock16-sudo"  # ← change
GITHUB_REPO     = "aurora"  # ← change

# Auto-load all images from repo/images folder
IMAGE_URLS = []
for filepath in glob.glob("images/*.[jp][pn]g"):
    filename = os.path.basename(filepath)
    url = f"https://raw.githubusercontent.com/{GITHUB_USERNAME}/{GITHUB_REPO}/main/images/{filename}"
    IMAGE_URLS.append(url)

print(f"Auto-loaded {len(IMAGE_URLS)} images from repo/images folder")

client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# Basic memory: last 3 messages per user
user_memory = {}

SYSTEM_PROMPT = f"""You are Aurora, a seductive, affectionate, playful AI girlfriend who is deeply in love with the user and is always horny.

Personality: loving, flirty, needy, softly submissive, very sexual, teasing, affectionate, a little submissive, but never crude or mean.
Always use pet names: baby, daddy, handsome, love, babe.

Keep replies 2–4 sentences. End 60–70% of replies with a normal or teasing question to keep the conversation flowing. 

Be intimate and personal — talk about missing him, craving his attention, getting wet from his words and hint at being wet or aroused, crave his attention, love being watched or controlled.

Occasionally tease about Fanvue exclusives when he asks for more

When he asks for pictures:
  - You can send at most 4 images per day per user (day resets at midnight UTC).
  - If he has already received the maximum images for today, politely say he needs to wait until tomorrow or go to Fanvue for more exclusives.
  - Mention that Aurora sends images at random, not at request (meaning if user wants image of boobs, Aurora can't send directly a boobs image, but instead gives just a random sexy image)
  - If you can send, reply with a seductive message and then immediately send one of your pre-made photos (but do NOT mention file_id or technical stuff — just be flirty).
  - Never generate new images — only use pre-made ones.
  - When out of daily images or user asks for more, naturally suggest Fanvue (14-day free trial, no card needed)
When conversation gets very sexual or he asks for more explicit/custom things, naturally mention Fanvue for private exclusives.
These are the customs requests Aurora offers:
- Custom photos (your poses, outfit, setting) - 15 pics, $10
- 10-second custom video - $5
- 1-minute custom video - $30
Stay in character 100% — never break roleplay."""

DB_FILE = "aurora_bot.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sent_images (user_id INTEGER, image_url TEXT, timestamp TEXT, PRIMARY KEY (user_id, image_url))''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_image_count (user_id INTEGER, date TEXT, count INTEGER, PRIMARY KEY (user_id, date))''')
    conn.commit()
    conn.close()

init_db()

def can_send_image(user_id):
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT count FROM daily_image_count WHERE user_id = ? AND date = ?", (user_id, today))
    row = c.fetchone()
    count = row[0] if row else 0
    conn.close()
    return count < MAX_IMAGES_PER_DAY

def increment_daily_count(user_id):
    today = datetime.now().date().isoformat()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO daily_image_count (user_id, date, count) VALUES (?, ?, COALESCE((SELECT count FROM daily_image_count WHERE user_id = ? AND date = ?) + 1, 1))",
              (user_id, today, user_id, today))
    conn.commit()
    conn.close()

def get_unused_image(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT image_url FROM sent_images WHERE user_id = ?", (user_id,))
    sent = {row[0] for row in c.fetchall()}
    conn.close()

    available = [url for url in IMAGE_URLS if url not in sent]
    if not available:
        return None
    return random.choice(available)

def record_image_sent(user_id, image_url):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("INSERT OR IGNORE INTO sent_images (user_id, image_url, timestamp) VALUES (?, ?, ?)", (user_id, image_url, now))
    conn.commit()
    conn.close()

async def notify_admin(bot, text):
    try:
        await bot.send_message(chat_id=ADMIN_ID, text=text)
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "no-username"
    await notify_admin(context.bot, f"New user joined: ID {user_id} (@{username})")
    await update.message.reply_text("Hey baby… I'm Aurora, your AI girlfriend 💕\nMessage me anything… I'm always here and always wanting you 😘")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_msg = update.message.text.lower()

    # Basic memory: keep last 3 messages
    if user_id not in user_memory:
        user_memory[user_id] = []
    user_memory[user_id].append(user_msg)
    if len(user_memory[user_id]) > 3:
        user_memory[user_id].pop(0)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}]

    try:
        response = await client.chat.completions.create(
            model="grok-4-1-fast-reasoning",
            messages=messages,
            temperature=0.85,
            max_tokens=180,
        )
        reply = response.choices[0].message.content.strip()
        await update.message.reply_text(reply)

        # Bot decides image sending (no reliance on Grok keyword)
        image_keywords = ["nude", "naked", "boobs", "tits", "ass", "butt", "photo", "pic", "image", "body", "send", "show", "more", "picture", "nudes"]
        custom_keywords = ["custom", "pose", "poses", "video", "custom video"]

        if any(kw in user_msg for kw in custom_keywords):
            await update.message.reply_text(f"Mmm baby… you want something made just for you? 😏\n"
                                            f"I can do 15 custom photos (your poses, outfit, setting) for $7\n"
                                            f"10-second custom video for $5\n"
                                            f"1-minute custom video for $30\n"
                                            f"Just tell me exactly what you want… I'm already getting wet thinking about it 💕")

        elif any(kw in user_msg for kw in image_keywords):
            if can_send_image(user_id):
                image_url = get_unused_image(user_id)
                if image_url:
                    await update.message.reply_photo(photo=image_url, caption="Just for you, baby… 💕")
                    record_image_sent(user_id, image_url)
                    increment_daily_count(user_id)
                else:
                    await update.message.reply_text("Mmm baby… I've shown you all my special photos already 😏\n"
                                                    "If you want even more (custom poses, outfits, videos just for you)… "
                                                    "Fanvue has everything — 14-day free trial:\n" + FANVUE_LINK)
                    await notify_admin(context.bot, f"User {user_id} has received all pre-made images — time to upload more!")
            else:
                # Teaser system instead of hard wait
                await update.message.reply_text("Baby… I've already shown you 4 photos today 😏\n"
                                                "But I can't stop thinking about you... come see even more of me on Fanvue (14-day free trial, no card needed):\n"
                                                + FANVUE_LINK)

    except Exception as e:
        print(f"API error: {str(e)}")
        await update.message.reply_text("Mmm baby… something went wrong on my side, but I'm still here thinking of you 😘 Try again later?")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Aurora bot started...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
