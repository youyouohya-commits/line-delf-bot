from groq import Groq
import json
import os
import re
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
app = Flask(__name__)
CACHE_FILE = "daily_cache.json"
user_states = {}


def save_daily(msg1, msg2):
    f = open(CACHE_FILE, "w", encoding="utf-8")
    json.dump({"date": str(date.today()), "message_1": msg1, "message_2": msg2}, f, ensure_ascii=False)
    f.close()


def load_daily():
    if not os.path.exists(CACHE_FILE):
        return None
    f = open(CACHE_FILE, "r", encoding="utf-8")
    data = json.load(f)
    f.close()
    return data


def generate_delf_practice():
    today = date.today().strftime("%d %B %Y")
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.8,
        max_tokens=2000,
        messages=[
            {
                "role": "system",
                "content": "Tu es un coach DELF B2. Reponds UNIQUEMENT en JSON valide sans markdown: {\"message_1\": \"sujet DELF B2 + vocabulaire B2 (verbes, noms, adverbes, expressions)\", \"message_2\": \"redaction modele minimum 250 mots\"}"
            },
            {
                "role": "user",
                "content": "Aujourd'hui, nous sommes le " + today + ". Genere le contenu DELF B2 du jour."
            }
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json|```", "", raw).strip()
    try:
        data = json.loads(raw)
        return data["message_1"], data["message_2"]
    except Exception as e:
        print("Error: " + str(e))
        return ("Generation failed", "Generation failed")


def grade_essay(essay, topic):
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=1500,
        messages=[
            {
                "role": "system",
                "content": "Tu es un correcteur DELF B2 expert. Evalue la redaction selon 5 criteres (note /25). Donne: note/25, points forts, erreurs + corrections, vocabulaire B2 recommande."
            },
            {
                "role": "user",
                "content": "Sujet: " + topic + "\n\nRedaction: " + essay
            }
        ]
    )
    return response.choices[0].message.content.strip()


def morning_push():
    msg1, msg2 = generate_delf_practice()
    save_daily(msg1, msg2)
    line_bot_api.broadcast(TextSendMessage(text=msg1))


def is_essay(text):
    return len(re.findall(r"\b\w+\b", text)) >= 80


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return "OK"


@app.route("/generate", methods=["GET"])
def generate():
    msg1, msg2 = generate_delf_practice()
    save_daily(msg1, msg2)
    return "Done! Today topic generated. Now send 完成 to your LINE bot!", 200


@app.route("/", methods=["GET"])
def index():
    return "DELF Bot is running!", 200


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text.strip()
    cache = load_daily()
    if "完成" in user_text or "✅" in user_text:
        if cache and cache["date"] == str(date.today()):
            user_states[user_id] = "awaiting_essay"
            reply = cache["message_2"]
        else:
            reply = "Not loaded yet, try later!"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    elif user_states.get(user_id) == "awaiting_essay" and is_essay(user_text):
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Correcting, please wait..."))
        topic = cache.get("message_1", "") if cache else ""
        result = grade_essay(user_text, topic)
        user_states[user_id] = None
        line_bot_api.push_message(user_id, TextSendMessage(text=result))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="Send 完成 or ✅ to get today's essay!"))


scheduler = BackgroundScheduler()
scheduler.add_job(morning_push, "cron", hour=8, minute=0)
scheduler.start()

if __name__ == "__main__":
    app.run(port=5000)
