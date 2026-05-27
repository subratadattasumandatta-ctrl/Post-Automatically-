import os
import asyncio
import logging
import threading
from flask import Flask, request, jsonify
from telegram import Update
from bot import build_application, start_scheduler, send_scheduled_post, store, TELEGRAM_BOT_TOKEN

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

tg_app = None
loop = None

@app.route("/")
def index():
    return jsonify({"status": "TG Auto Poster Bot is running!"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "posts_sent": store.get("post_count", 0)})

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    global tg_app, loop
    if tg_app is None or loop is None:
        return jsonify({"error": "Bot not ready"}), 503
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, tg_app.bot)
        # Use the persistent event loop
        future = asyncio.run_coroutine_threadsafe(tg_app.process_update(update), loop)
        future.result(timeout=30)
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

async def bot_main():
    global tg_app
    tg_app = build_application()
    await tg_app.initialize()
    await tg_app.start()

    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        webhook_url = f"{render_url}/webhook/{TELEGRAM_BOT_TOKEN}"
        await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info(f"✅ Webhook set: {webhook_url}")

    start_scheduler()
    logger.info("✅ Application started")

    # Keep running forever
    await asyncio.Event().wait()

def run_bot_loop():
    global loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(bot_main())

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    import datetime
    print(f"===== Application Startup at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")

    # Run bot in background thread with its own event loop
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()

    # Wait for bot to initialize
    import time
    time.sleep(5)

    # Run Flask in main thread
    run_flask()
    
