import os
import asyncio
import logging
import json
import base64
import httpx
from telegram import Bot, Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GROQ_API_KEY       = os.environ.get("GROQ_API_KEY", "")
POSTING_CHANNEL    = os.environ.get("POSTING_CHANNEL", "")
ADMIN_ID           = int(os.environ.get("ADMIN_ID", "0"))  # Sirf admin use kar sakta hai

# Conversation states
WAIT_IMAGES, WAIT_TITLE, WAIT_DOWNLOAD, WAIT_INTERVAL = range(4)
ADD_IMAGES = 10

# In-memory store
store: dict = {}

scheduler = AsyncIOScheduler()

# ─── Admin Check ──────────────────────────────────────────────────────────────

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID

async def not_admin_msg(update: Update):
    await update.message.reply_text("⛔ Sirf admin is bot ko use kar sakta hai!")

# ─── Groq API ─────────────────────────────────────────────────────────────────

async def call_groq(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "You are a Telegram content expert. Always respond with valid JSON only, no markdown, no extra text."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.9,
        "max_tokens": 600,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        if r.status_code != 200:
            logger.error(f"Groq error {r.status_code}: {r.text}")
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# ─── Content Generator ────────────────────────────────────────────────────────

async def generate_content(base_title: str, post_count: int) -> dict:
    variations = [
        "Full Movie HD", "Hindi Dubbed", "Official Trailer", "Watch Online Free",
        "Download Now", "4K Ultra HD", "Box Office Collection", "Movie Review",
        "Behind The Scenes", "Full Movie 2025", "Hindi Dubbed 1080p", "Teaser",
        "First Look", "Release Date", "Streaming Now"
    ]
    variation = variations[post_count % len(variations)]

    prompt = f"""Generate viral Telegram channel post content.

Base Title: "{base_title}"
Title Variation to use: "{variation}"
Post Number: {post_count + 1}

Generate:
1. A unique short title combining base title + variation (must be different every time)
2. Exactly 8-10 trending hashtags related to the title (with # symbol)
3. Exactly 8-10 SEO keyword phrases (each on new line, real search queries people type)

Return ONLY this JSON (no markdown, no backticks):
{{
  "title": "unique title with {variation}",
  "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6 #tag7 #tag8 #tag9 #tag10",
  "keywords": "keyword phrase 1\\nkeyword phrase 2\\nkeyword phrase 3\\nkeyword phrase 4\\nkeyword phrase 5\\nkeyword phrase 6\\nkeyword phrase 7\\nkeyword phrase 8"
}}"""

    try:
        response = await call_groq(prompt)
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        data = json.loads(clean.strip())
        return data
    except Exception as e:
        logger.error(f"Content gen error: {e}")
        return {
            "title": f"{base_title} {variation}",
            "hashtags": f"#{base_title.replace(' ','')} #HindiMovie #Bollywood #Trending #Viral #FullMovie #HD #Download #Watch #2025",
            "keywords": f"{base_title} full movie\n{base_title} hindi dubbed\n{base_title} download\n{base_title} watch online\n{base_title} trailer\n{base_title} {variation}\n{base_title} 2025\n{base_title} HD"
        }

# ─── Scheduled Post ───────────────────────────────────────────────────────────

async def send_scheduled_post():
    if not store.get("base_title"):
        logger.info("No config, skipping post.")
        return

    channel_id    = POSTING_CHANNEL
    base_title    = store["base_title"]
    images        = store.get("images", [])
    post_count    = store.get("post_count", 0)
    download_link = store.get("download_link", "")

    logger.info(f"Generating post #{post_count + 1}")
    content = await generate_content(base_title, post_count)

    title    = content["title"]
    hashtags = content["hashtags"]
    keywords = content["keywords"]

    # Clean special chars to avoid Markdown parse errors
    title_clean = title.replace("*","").replace("_","").replace("`","").replace("[","").replace("]","")
    caption = (
        f"{title_clean}\n\n"
        f"Download Link:\n{download_link}\n\n"
        f"{hashtags}\n\n"
        f"{keywords}"
    )

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        if images:
            img_index = post_count % len(images)
            img_bytes = base64.b64decode(images[img_index])
            await bot.send_photo(
                chat_id=channel_id,
                photo=img_bytes,
                caption=caption,
            )
            logger.info(f"✅ Post #{post_count+1} sent | Image #{img_index+1} | Title: {title}")
        else:
            await bot.send_message(chat_id=channel_id, text=caption)
            logger.info(f"✅ Post #{post_count+1} sent (no image)")

        store["post_count"] = post_count + 1

    except Exception as e:
        logger.error(f"Send error: {e}")

# ─── Scheduler ────────────────────────────────────────────────────────────────

def restart_scheduler(interval_minutes: int):
    if scheduler.get_job("auto_post"):
        scheduler.remove_job("auto_post")
    scheduler.add_job(
        send_scheduled_post,
        trigger="interval",
        minutes=interval_minutes,
        id="auto_post",
        replace_existing=True,
    )
    logger.info(f"⏰ Scheduler set: every {interval_minutes} minutes.")

def start_scheduler():
    if not scheduler.running:
        scheduler.start()
    logger.info("⏰ Scheduler engine started.")

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return
    await update.message.reply_text(
        "👋 *TG Auto Poster Bot*\n\n"
        "*Commands:*\n"
        "📌 /setup — Naya setup karo\n"
        "🖼️ /addimages — Aur images add karo\n"
        "⏰ /settime — Post interval change karo\n"
        "📊 /status — Status dekho\n"
        "📤 /postnow — Abhi test post bhejo\n"
        "⛔ /stop — Posting band karo",
        parse_mode="Markdown"
    )

# ─── /setup conversation ──────────────────────────────────────────────────────

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return ConversationHandler.END
    context.user_data["temp_images"] = []
    await update.message.reply_text(
        "🖼️ *Step 1/4 — Images*\n\n"
        "Saari images ek ek karke bhejo *(10-15 images)*\n"
        "Jab saari images bhej do toh */done* likho ✅",
        parse_mode="Markdown"
    )
    return WAIT_IMAGES

async def got_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo     = update.message.photo[-1]
    file      = await photo.get_file()
    img_bytes = await file.download_as_bytearray()
    context.user_data.setdefault("temp_images", []).append(base64.b64encode(img_bytes).decode())
    count = len(context.user_data["temp_images"])
    await update.message.reply_text(f"✅ Image {count} save! Aur bhejo ya */done* likho.", parse_mode="Markdown")
    return WAIT_IMAGES

async def images_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    imgs = context.user_data.get("temp_images", [])
    if not imgs:
        await update.message.reply_text("⚠️ Koi image nahi! Pehle images bhejo.")
        return WAIT_IMAGES
    context.user_data["images"] = imgs
    await update.message.reply_text(
        f"✅ *{len(imgs)} images save!*\n\n"
        f"✏️ *Step 2/4 — Base Title*\n\n"
        f"Movie/content ka base title bhejo\n"
        f"_(Example: Toxic Movie)_",
        parse_mode="Markdown"
    )
    return WAIT_TITLE

async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Title: *{context.user_data['title']}*\n\n"
        f"🔗 *Step 3/4 — Download Link*\n\n"
        f"Post mein dikhane wala download link bhejo\n"
        f"_(Example: https://t.me/filmyhubofficial/360)_",
        parse_mode="Markdown"
    )
    return WAIT_DOWNLOAD

async def got_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["download_link"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Download link save!\n\n"
        f"⏰ *Step 4/4 — Post Interval*\n\n"
        f"Kitne *minutes* baad post hoga? Number bhejo\n"
        f"_(Example: 60 = 1 ghanta, 30 = 30 minute, 1440 = 1 din)_",
        parse_mode="Markdown"
    )
    return WAIT_INTERVAL

async def got_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text.strip())
        if minutes < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Sirf number bhejo! _(Example: 60)_", parse_mode="Markdown")
        return WAIT_INTERVAL

    store.clear()
    store["base_title"]    = context.user_data["title"]
    store["download_link"] = context.user_data["download_link"]
    store["images"]        = context.user_data.get("images", [])
    store["post_count"]    = 0
    store["interval"]      = minutes

    restart_scheduler(minutes)

    await update.message.reply_text(
        f"🎉 *Setup Complete!*\n\n"
        f"📢 Posting Channel: `{POSTING_CHANNEL}`\n"
        f"🎬 Base Title: `{store['base_title']}`\n"
        f"🔗 Download Link: `{store['download_link']}`\n"
        f"🖼️ Images: *{len(store['images'])}* (rotate hongi)\n"
        f"⏰ Interval: *har {minutes} minute* mein post\n\n"
        f"Test ke liye */postnow* bhejo 🚀",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup cancel.")
    return ConversationHandler.END

# ─── /settime conversation ────────────────────────────────────────────────────

WAIT_NEW_TIME = 20

async def settime_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return ConversationHandler.END
    if not store.get("base_title"):
        await update.message.reply_text("⚠️ Pehle /setup karo!")
        return ConversationHandler.END
    await update.message.reply_text(
        f"⏰ Abhi interval: *{store.get('interval', '?')} minutes*\n\n"
        f"Naya interval (minutes mein) bhejo:\n"
        f"_(60=1hr, 120=2hr, 1440=1din)_",
        parse_mode="Markdown"
    )
    return WAIT_NEW_TIME

async def got_new_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        minutes = int(update.message.text.strip())
        if minutes < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("⚠️ Sirf number bhejo!")
        return WAIT_NEW_TIME
    store["interval"] = minutes
    restart_scheduler(minutes)
    await update.message.reply_text(f"✅ Interval update! Ab har *{minutes} minute* mein post hoga.", parse_mode="Markdown")
    return ConversationHandler.END

# ─── /addimages conversation ──────────────────────────────────────────────────

async def addimages_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return ConversationHandler.END
    if not store.get("base_title"):
        await update.message.reply_text("⚠️ Pehle /setup karo!")
        return ConversationHandler.END
    context.user_data["temp_images"] = []
    await update.message.reply_text(
        f"🖼️ Abhi *{len(store.get('images', []))}* images hain.\n"
        f"Nayi images bhejo → */done* likho.",
        parse_mode="Markdown"
    )
    return ADD_IMAGES

async def addimages_got(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]
    file  = await photo.get_file()
    img_bytes = await file.download_as_bytearray()
    context.user_data.setdefault("temp_images", []).append(base64.b64encode(img_bytes).decode())
    count = len(context.user_data["temp_images"])
    await update.message.reply_text(f"✅ {count} nayi image. Aur bhejo ya */done*.", parse_mode="Markdown")
    return ADD_IMAGES

async def addimages_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_imgs = context.user_data.get("temp_images", [])
    store.setdefault("images", []).extend(new_imgs)
    await update.message.reply_text(
        f"✅ *{len(new_imgs)} images add!*\nTotal: *{len(store['images'])}* images",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ─── Other commands ───────────────────────────────────────────────────────────

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return
    if not store.get("base_title"):
        await update.message.reply_text("⚠️ Koi setup nahi.\n/setup karo pehle.")
        return
    total  = len(store.get("images", []))
    count  = store.get("post_count", 0)
    nextimg = (count % total) + 1 if total else 0
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"📢 Channel: `{POSTING_CHANNEL}`\n"
        f"🎬 Title: `{store.get('base_title')}`\n"
        f"🔗 Download Link: `{store.get('download_link')}`\n"
        f"🖼️ Total Images: *{total}*\n"
        f"🔄 Agli image: *#{nextimg}*\n"
        f"📤 Posts Sent: *{count}*\n"
        f"⏰ Interval: *{store.get('interval', '?')} minutes*\n"
        f"🟢 Status: *Active*",
        parse_mode="Markdown"
    )

async def postnow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return
    if not store.get("base_title"):
        await update.message.reply_text("⚠️ Pehle /setup karo!")
        return
    await update.message.reply_text("📤 Post generate ho raha hai...")
    await send_scheduled_post()
    count = store.get("post_count", 0)
    total = len(store.get("images", []))
    used  = ((count - 1) % total) + 1 if total else 0
    await update.message.reply_text(
        f"✅ Post #{count} channel mein chala gaya!\n"
        f"🖼️ Image #{used} use hui",
        parse_mode="Markdown"
    )

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await not_admin_msg(update)
        return
    if scheduler.get_job("auto_post"):
        scheduler.remove_job("auto_post")
    store.clear()
    await update.message.reply_text("⛔ Posting band. Dobara ke liye /setup karo.")

# ─── Build Application ────────────────────────────────────────────────────────

def build_application():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            WAIT_IMAGES:   [MessageHandler(filters.PHOTO, got_image),
                            CommandHandler("done", images_done)],
            WAIT_TITLE:    [MessageHandler(filters.TEXT & ~filters.COMMAND, got_title)],
            WAIT_DOWNLOAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_download)],
            WAIT_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_interval)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    settime_conv = ConversationHandler(
        entry_points=[CommandHandler("settime", settime_start)],
        states={
            WAIT_NEW_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_new_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    addimg_conv = ConversationHandler(
        entry_points=[CommandHandler("addimages", addimages_start)],
        states={
            ADD_IMAGES: [MessageHandler(filters.PHOTO, addimages_got),
                         CommandHandler("done", addimages_done)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("postnow", postnow_cmd))
    application.add_handler(CommandHandler("stop", stop_cmd))
    application.add_handler(setup_conv)
    application.add_handler(settime_conv)
    application.add_handler(addimg_conv)

    return application
    
