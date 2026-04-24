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


def clean_text(text):
    if not text:
        return ""
    text = str(text)
    text = text.replace("\r", "\n")
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    return text


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
    system_msg = "Tu es un coach DELF B2. Tu dois repondre en JSON uniquement. Le JSON doit avoir exactement deux cles: message_1 et message_2. message_1 contient le sujet et vocabulaire. message_2 contient la redaction modele. Ne mets aucun markdown, aucun backtick."
    user_msg = "Date: " + today + ". Genere un sujet DELF B2 avec vocabulaire et une redaction modele de 250 mots minimum. Reponds en JSON uniquement avec les cles message_1 et message_2."

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.7,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"```json", "", raw)
    raw = re.sub(r"```", "", raw)
    raw = raw.strip()

    try:
        data = json.loads(raw)
        msg1 = clean_text(data.get("message_1", ""))
        msg2 = clean_text(data.get("message_2", ""))
        if msg1 and msg2:
            return msg1, msg2
        else:
            return "Sujet non disponible aujourd'hui.", "Redaction non disponible."
    except Exception as e:
        print("JSON Error: " + str(e))
        print("Raw: " + raw[:200])
        return "Sujet non disponible aujourd'hui.", "Redaction non disponible."


def grade_essay(essay, topic):
    system_msg = "Tu es un correcteur DELF B2 expert. Evalue la redaction et donne: note sur 25, points forts, erreurs avec corrections, vocabulaire B2 recommande."
    user_msg = "Sujet: " + topic + "\n\nRedaction de l'etudiant:\n" + essay

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=1500,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg}
        ]
    )
    result = response.choices[0].message.content.strip()
    return clean_text(result)


def morning_push():
    msg1, msg2 = generate_delf_practice()
    save_daily(msg1, msg2)
    line_bot_api.broadcast(TextSendMessage(text=msg1))


def is_essay(text):
    return len(re.findall(r"\b\w+\b", text)) >= 80


def safe_reply(reply_token, text):
    try:
        text = clean_text(text)
        if not text:
            text = "Erreur: message vide."
        line_bot_api.reply_message(reply_token, TextSendMessage(text=text))
    except Exception as e:
        print("Reply error: " + str(e))


def safe_push(user_id, text):
    try:
        text = clean_text(text)
        if not text:
            text = "Erreur: message vide."
        line_bot_api.push_message(user_id, TextSendMessage(text=text))
    except Exception as e:
        print("Push error: " + str(e))


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
    return "Done! msg1=" + msg1[:50] + "...", 200


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
            reply = cache.get("message_2", "")
            if not reply:
                reply = "Contenu non disponible."
            safe_reply(event.reply_token, reply)
        else:
            safe_reply(event.reply_token, "Pas encore charge, reessaie plus tard!")

    elif user_states.get(user_id) == "awaiting_essay" and is_essay(user_text):
        safe_reply(event.reply_token, "Correction en cours, patiente 10 secondes...")
        topic = cache.get("message_1", "") if cache else ""
        result = grade_essay(user_text, topic)
        user_states[user_id] = None
        safe_push(user_id, result)

    else:
        safe_reply(event.reply_token, "Envoie 完成 pour recevoir la redaction modele du jour!")


scheduler = BackgroundScheduler()
scheduler.add_job(morning_push, "cron", hour=8, minute=0)
scheduler.start()

if __name__ == "__main__":
    app.run(port=5000)
