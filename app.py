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

# Global telegram app
tg_app = None

@app.route("/")
def index():
    return jsonify({"status": "TG Auto Poster Bot is running!"})

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

@app.route(f"/webhook/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    """Telegram webhook endpoint."""
    global tg_app
    if tg_app is None:
        return jsonify({"error": "Bot not ready"}), 503
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, tg_app.bot)
        asyncio.run(tg_app.process_update(update))
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

async def setup_webhook():
    """Set Telegram webhook."""
    global tg_app
    tg_app = build_application()
    await tg_app.initialize()
    await tg_app.start()

    render_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if render_url:
        webhook_url = f"{render_url}/webhook/{TELEGRAM_BOT_TOKEN}"
        await tg_app.bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        logger.info(f"✅ Webhook set: {webhook_url}")
    else:
        logger.warning("⚠️ RENDER_EXTERNAL_URL not set! Webhook not configured.")

    start_scheduler()
    logger.info("✅ Application started")

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    import datetime
    print(f"===== Application Startup at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====")
    # Setup webhook
    asyncio.run(setup_webhook())
    # Run Flask
    run_flask()
    
