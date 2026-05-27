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
POSTING_CHANNEL    = os.environ.get("POSTING_CHANNEL", "")  # Channel jahan bot post karega

# Conversation states
WAIT_IMAGES, WAIT_TITLE, WAIT_DOWNLOAD = range(3)

# In-memory store
store: dict = {}
# store keys:
#   channel_id, channel_link, base_title
#   images: list of base64 strings
#   post_count: int
#   collecting_images: bool (True while user is sending images)

# ─── Claude API ───────────────────────────────────────────────────────────────

async def ask_claude(prompt: str) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
        if r.status_code != 200:
            logger.error(f"Groq error {r.status_code}: {r.text}")
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


async def generate_post_content(base_title: str, post_count: int) -> dict:
    prompt = f"""You are a Telegram channel content expert. Generate viral Telegram post content.

Base Title: "{base_title}"
Post Number: {post_count + 1}

Rules:
1. Create a SHORT unique title (1 line only, vary each time: add Hindi Dubbed, Full Movie, HD, Trailer, Review, 2025, Watch Online, Download, etc.)
2. Generate exactly 5 trending SEO keyword LINES (each on new line, like search queries people type)
3. Generate 6-8 hashtags (with # symbol, space separated, relevant to title)

Respond ONLY in this exact JSON format (no markdown, no extra text):
{{
  "title": "Short Unique Title Here",
  "keywords": "keyword line 1\nkeyword line 2\nkeyword line 3\nkeyword line 4\nkeyword line 5",
  "hashtags": "#tag1 #tag2 #tag3 #tag4 #tag5 #tag6 #tag7"
}}"""

    response = await ask_claude(prompt)
    try:
        clean = response.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        logger.error(f"JSON parse error: {e}")
        return {
            "title": f"{base_title} | Part {post_count + 1}",
            "keywords": f"{base_title} full movie\n{base_title} hindi dubbed\n{base_title} download\n{base_title} watch online\n{base_title} trailer 2025",
            "hashtags": "#trending #viral #movie #hindi #latest",
        }

# ─── Scheduled Post ───────────────────────────────────────────────────────────

async def send_scheduled_post():
    if not store.get("channel_id"):
        return

    channel_id   = POSTING_CHANNEL or store.get("channel_id", "")
    base_title   = store["base_title"]
    images       = store.get("images", [])
    post_count   = store.get("post_count", 0)
    channel_link = store.get("download_link", "")  # Download link from bot

    logger.info(f"Generating post #{post_count + 1}")
    content = await generate_post_content(base_title, post_count)

    caption = (
        f"*{content['title']}*\n\n"
        f"Download Link:\n"
        f"{channel_link}\n\n"
        f"{content['hashtags']}\n\n"
        f"{content['keywords']}"
    )

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    try:
        if images:
            # Rotate images: post_count % total images
            img_index = post_count % len(images)
            img_b64   = images[img_index]
            img_bytes = base64.b64decode(img_b64)
            await bot.send_photo(
                chat_id=channel_id,
                photo=img_bytes,
                caption=caption,
                parse_mode="Markdown",
            )
            logger.info(f"✅ Post #{post_count + 1} sent with image #{img_index + 1}/{len(images)}")
        else:
            await bot.send_message(chat_id=channel_id, text=caption, parse_mode="Markdown")
            logger.info(f"✅ Post #{post_count + 1} sent (no image)")

        store["post_count"] = post_count + 1

    except Exception as e:
        logger.error(f"Post error: {e}")

# ─── Scheduler ────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()

def start_scheduler():
    scheduler.add_job(send_scheduled_post, trigger="interval", hours=1,
                      id="hourly_post", replace_existing=True)
    scheduler.start()
    logger.info("⏰ Scheduler started.")

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *TG Auto Poster Bot*\n\n"
        "Commands:\n"
        "📌 /setup — Naya channel setup karo\n"
        "🖼️ /addimages — Aur images add karo\n"
        "📊 /status — Current status dekho\n"
        "📤 /postnow — Abhi ek post bhejo\n"
        "⛔ /stop — Posting band karo",
        parse_mode="Markdown"
    )

# ─── /setup conversation ──────────────────────────────────────────────────────

async def setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["temp_images"] = []
    await update.message.reply_text(
        "🖼️ *Step 1/3 — Images*\n\n"
        "Saari images ek ek karke bhejo *(10-15 images)*\n\n"
        "Jab saari images bhej do toh */done* likho ✅",
        parse_mode="Markdown"
    )
    return WAIT_IMAGES

async def got_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo     = update.message.photo[-1]
    file      = await photo.get_file()
    img_bytes = await file.download_as_bytearray()
    img_b64   = base64.b64encode(img_bytes).decode()

    if "temp_images" not in context.user_data:
        context.user_data["temp_images"] = []

    context.user_data["temp_images"].append(img_b64)
    count = len(context.user_data["temp_images"])

    await update.message.reply_text(
        f"✅ Image {count} mil gayi!\n"
        f"Aur images bhejo ya */done* likho ({count} images abhi tak)",
        parse_mode="Markdown"
    )
    return WAIT_IMAGES

async def images_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    imgs = context.user_data.get("temp_images", [])
    if not imgs:
        await update.message.reply_text("⚠️ Koi image nahi mili! Pehle images bhejo.")
        return WAIT_IMAGES

    context.user_data["images"] = imgs
    await update.message.reply_text(
        f"✅ *{len(imgs)} images save ho gayi!*\n\n"
        f"✏️ *Step 2/3 — Title*\n\nAb channel ka *base title* bhejo\n"
        f"_(Example: Toxic Hindi Movie)_",
        parse_mode="Markdown"
    )
    return WAIT_TITLE

async def got_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ Title: *{context.user_data['title']}*\n\n"
        f"🔗 *Step 3/3 — Download Link*\n\n"
        f"Post mein jo *Download Link* dikhana hai woh bhejo\n"
        f"_(Example: https://t.me/filmyhubofficial/360)_",
        parse_mode="Markdown"
    )
    return WAIT_DOWNLOAD

async def got_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()

    # Extract channel ID from link
    if "t.me/" in link:
        part = link.split("t.me/")[1].strip("/")
        channel_id = link if part.startswith("+") else "@" + part
    else:
        channel_id = link

    store.clear()
    store["channel_id"]   = channel_id
    store["channel_link"] = link
    store["base_title"]   = context.user_data["title"]
    store["images"]       = context.user_data.get("images", [])
    store["post_count"]   = 0

    total_imgs = len(store["images"])

    await update.message.reply_text(
        f"🎉 *Setup Complete!*\n\n"
        f"📢 Channel: `{channel_id}`\n"
        f"🎬 Title: `{store['base_title']}`\n"
        f"🖼️ Images: *{total_imgs} images* (rotate hongi)\n\n"
        f"⏰ Har *1 ghante* mein auto post hoga!\n"
        f"Pehla post: */postnow* se test karo 🚀",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Setup cancel.")
    return ConversationHandler.END

# ─── /addimages conversation ──────────────────────────────────────────────────

ADD_IMAGES = 10

async def addimages_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not store.get("channel_id"):
        await update.message.reply_text("⚠️ Pehle /setup karo!")
        return ConversationHandler.END
    context.user_data["temp_images"] = []
    await update.message.reply_text(
        f"🖼️ *Images Add Karo*\n\n"
        f"Abhi {len(store.get('images', []))} images hain.\n"
        f"Nayi images bhejo, phir */done* likho.",
        parse_mode="Markdown"
    )
    return ADD_IMAGES

async def addimages_got(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo     = update.message.photo[-1]
    file      = await photo.get_file()
    img_bytes = await file.download_as_bytearray()
    context.user_data.setdefault("temp_images", []).append(base64.b64encode(img_bytes).decode())
    count = len(context.user_data["temp_images"])
    await update.message.reply_text(f"✅ {count} nayi image(s). Aur bhejo ya */done* likho.", parse_mode="Markdown")
    return ADD_IMAGES

async def addimages_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_imgs = context.user_data.get("temp_images", [])
    store.setdefault("images", []).extend(new_imgs)
    await update.message.reply_text(
        f"✅ *{len(new_imgs)} images add ho gayi!*\n"
        f"Total images: *{len(store['images'])}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ─── Other commands ───────────────────────────────────────────────────────────

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not store.get("channel_id"):
        await update.message.reply_text("⚠️ Koi setup nahi.\n/setup karo pehle.")
        return
    total_imgs = len(store.get("images", []))
    post_count = store.get("post_count", 0)
    next_img   = (post_count % total_imgs) + 1 if total_imgs else 0
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"📢 Posting Channel: `{POSTING_CHANNEL}`\n"
        f"🔗 Download Link: `{store.get('download_link', '—')}`\n"
        f"🎬 Title: `{store.get('base_title')}`\n"
        f"🖼️ Total Images: *{total_imgs}*\n"
        f"🔄 Agle post mein image: *#{next_img}*\n"
        f"📤 Posts Sent: *{post_count}*\n"
        f"⏰ Status: *Active*",
        parse_mode="Markdown"
    )

async def postnow_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not store.get("channel_id"):
        await update.message.reply_text("⚠️ Pehle /setup karo!")
        return
    await update.message.reply_text("📤 Post bhej raha hoon...")
    await send_scheduled_post()
    total = len(store.get("images", []))
    await update.message.reply_text(
        f"✅ Post #{store.get('post_count', 0)} channel mein chala gaya!\n"
        f"🖼️ Image #{((store.get('post_count',1)-1) % total)+1 if total else 0} use hui"
    )

async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    store.clear()
    await update.message.reply_text("⛔ Posting band. Dobara ke liye /setup karo.")

# ─── Build Application ────────────────────────────────────────────────────────

def build_application():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("setup", setup_start)],
        states={
            WAIT_IMAGES: [
                MessageHandler(filters.PHOTO, got_image),
                CommandHandler("done", images_done),
            ],
            WAIT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_title)],
            WAIT_DOWNLOAD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_link)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    addimg_conv = ConversationHandler(
        entry_points=[CommandHandler("addimages", addimages_start)],
        states={
            ADD_IMAGES: [
                MessageHandler(filters.PHOTO, addimages_got),
                CommandHandler("done", addimages_done),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("postnow", postnow_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(setup_conv)
    app.add_handler(addimg_conv)

    return app
