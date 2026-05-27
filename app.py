import os
import asyncio
import logging
import threading
from flask import Flask, jsonify
from bot import build_application, start_scheduler, send_scheduled_post, store

logger = logging.getLogger(__name__)
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"status": "TG Auto Poster Bot is running! Open Telegram and send /start to your bot."})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "posts_sent": store.get("post_count", 0)})

@app.route("/status")
def status():
    return jsonify({
        "channel_id":  store.get("channel_id"),
        "base_title":  store.get("base_title"),
        "post_count":  store.get("post_count", 0),
    })

def run_flask():
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

async def main():
    # Start scheduler
    start_scheduler()
    # Start Flask in background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    # Start Telegram bot (polling)
    tg_app = build_application()
    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)
    logger.info("🤖 Telegram Bot polling started!")
    # Keep running forever
    await asyncio.Event().wait()

if __name__ == "__main__":
    print("===== Application Startup at", __import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "=====")
    asyncio.run(main())
    
