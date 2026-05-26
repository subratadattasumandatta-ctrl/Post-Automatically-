import asyncio
import random
import threading
import time
import os
from telebot import TeleBot
from fastapi import FastAPI
import uvicorn

# --- CONFIGURATION ---
BOT_TOKEN = "8671313298:AAHj3Bvt3pVq9Mnuhy2mxjUmiB2w4c-NQ3s"
CHANNEL_ID = -1004167796969
ADMIN_ID = 7062026157

bot = TeleBot(BOT_TOKEN)
api_app = FastAPI()

# --- IN-MEMORY STORAGE ---
campaign_data = {
    "title": "",
    "link": "",
    "timer": 60,
    "status": "idle",
    "images": []
}

titles_v = ["{} Hindi Movie", "{} Full Movie Dubbed", "{} New Update"]
keywords_v = ["{} movie download link", "{} hindi dubbed watch online"]
hashtags_v = ["#{}", "#{}Movie", "#Trending"]

# --- CORE POSTING LOOP ---
def start_posting_loop():
    print("🚀 Auto-posting loop active...")
    while True:
        try:
            if campaign_data["status"] == "running" and campaign_data["images"]:
                base_title = campaign_data["title"]
                clean_tag = base_title.replace(" ", "")
                timer_seconds = campaign_data["timer"] * 60
                
                img_to_send = random.choice(campaign_data["images"])
                current_title = random.choice(titles_v).format(base_title)
                current_keyword = random.choice(keywords_v).format(base_title)
                
                sampled_tags = random.sample(hashtags_v, 2)
                current_tag = f"{sampled_tags[0].format(clean_tag)} {sampled_tags[1].format('New')}"

                caption = f"🎬 **{current_title}**\n\n🔍 {current_keyword}\n\n🔗 **Link:** {campaign_data['link']}\n\n{current_tag}"

                bot.send_photo(chat_id=CHANNEL_ID, photo=img_to_send, caption=caption, parse_mode="Markdown")
                print(f"✅ Post sent to channel: {CHANNEL_ID}")
                
                time.sleep(timer_seconds)
            else:
                time.sleep(5)
        except Exception as e:
            print(f"❌ Loop Error: {e}")
            time.sleep(10)

# --- TELEGRAM HANDLERS ---
@bot.message_handler(commands=['start', 'newpost'])
def start_campaign(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    campaign_data["title"] = ""
    campaign_data["link"] = ""
    campaign_data["timer"] = 60
    campaign_data["status"] = "waiting_for_details"
    campaign_data["images"] = []
    
    bot.reply_to(message, "🔐 **Admin Verified (Render Engine Active)!**\n\nNaya campaign set karne ke liye pehle **Title aur Link** is format mein bhejiye:\n\n`Movie Name | https://t.me/link`")

@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text(message):
    if message.from_user.id != ADMIN_ID:
        return
        
    status = campaign_data["status"]
    
    if status == "waiting_for_details":
        if "|" not in message.text:
            bot.reply_to(message, "❌ Format galat hai! `|` symbol use karein.\nExample: `Toxic Movie | https://t.me/link`")
            return
        title, link = message.text.split("|")
        campaign_data["title"] = title.strip()
        campaign_data["link"] = link.strip()
        campaign_data["status"] = "waiting_for_timer"
        bot.reply_to(message, "✅ Saved! Ab post ka interval (**Minutes** mein) batayein (Jaise: `30` ya `60`):")
        
    elif status == "waiting_for_timer":
        try:
            timer_val = int(message.text)
            campaign_data["timer"] = timer_val
            campaign_data["status"] = "waiting_for_images"
            bot.reply_to(message, "✅ Timer Set! Ab ek-ek karke **Images** bhejiye. Sab bhej dene ke baad **/done** likhein.")
        except ValueError:
            bot.reply_to(message, "❌ Kripya sirf number type karein.")
            
    elif message.text == "/done" and status == "waiting_for_images":
        if not campaign_data["images"]:
            bot.reply_to(message, "⚠️ Kam se kam 1 image upload kijiye!")
            return
        campaign_data["status"] = "running"
        bot.reply_to(message, f"🚀 **Campaign Started!** Har {campaign_data['timer']} minutes mein automatic post jati rahegi.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    if message.from_user.id != ADMIN_ID:
        return
    
    if campaign_data["status"] == "waiting_for_images":
        file_id = message.photo[-1].file_id
        campaign_data["images"].append(file_id)
        bot.reply_to(message, f"📥 Image {len(campaign_data['images'])} saved! Aur bhejien ya `/done` likhein.")

@api_app.get("/")
def home():
    return {"status": "Render Engine Running", "campaign": campaign_data["status"]}

def run_bot_forever():
    print("🤖 Starting Bot Polling Engine on Render...")
    while True:
        try:
            bot.remove_webhook()
            bot.polling(non_stop=True, interval=2, timeout=60, skip_pending=True)
        except Exception as e:
            print(f"🔄 Reconnecting Bot due to error: {e}")
            time.sleep(5)

async def main():
    t1 = threading.Thread(target=run_bot_forever)
    t2 = threading.Thread(target=start_posting_loop)
    t1.daemon = True
    t2.daemon = True
    t1.start()
    t2.start()
    
    # Render dynamic port management
    port = int(os.environ.get("PORT", 7860))
    config = uvicorn.Config(app=api_app, host="0.0.0.0", port=port)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
