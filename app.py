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


def format_message(sujet, mots, expressions):
    msg = "🎯 Sujet du jour\n\n"
    msg += sujet.strip() + "\n\n"
    msg += "📚 Les mots cles\n\n"
    for mot in mots:
        msg += "- " + mot.strip() + "\n"
    msg += "\n💬 Les expressions utiles\n\n"
    for exp in expressions:
        msg += "- " + exp.strip() + "\n"
    return msg.strip()


def generate_delf_practice():
    today = date.today().strftime("%d %B %Y")

    system_msg = (
        "Tu es un coach DELF B2. "
        "Reponds UNIQUEMENT en JSON valide avec exactement ces cles: "
        "sujet, mots_cles, expressions, redaction. "
        "sujet: string avec le sujet DELF B2. "
        "mots_cles: liste de 8 mots importants (array de strings). "
        "expressions: liste de 6 expressions utiles (array de strings). "
        "redaction: string avec la redaction modele de 250 mots minimum. "
        "Ne mets aucun markdown ni backtick."
    )

    user_msg = "Date: " + today + ". Genere le contenu DELF B2 du jour en JSON."

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
        sujet = data.get("sujet", "")
        mots = data.get("mots_cles", [])
        expressions = data.get("expressions", [])
        redaction = data.get("redaction", "")

        msg1 = format_message(sujet, mots, expressions)
        msg2 = "Redaction modele\n\n" + clean_text(redaction)

        return msg1, msg2

    except Exception as e:
        print("JSON Error: " + str(e))
        print("Raw: " + raw[:300])
        return ("Generation failed", "Generation failed")


def grade_essay(essay, topic):
    system_msg = (
        "Tu es un correcteur DELF B2 expert. "
        "Reponds UNIQUEMENT en JSON valide avec ces cles: "
        "note, respect_consigne, organisation, grammaire, vocabulaire, style, "
        "points_forts, erreurs, vocabulaire_recommande. "
        "note: string comme 18/25. "
        "respect_consigne: score comme 4/5. "
        "organisation: score comme 3/5. "
        "grammaire: score comme 4/5. "
        "vocabulaire: score comme 3/5. "
        "style: score comme 4/5. "
        "points_forts: liste de 3 points forts (array de strings). "
        "erreurs: liste de 3 erreurs avec correction (array de strings). "
        "vocabulaire_recommande: liste de 5 mots B2 recommandes (array de strings). "
        "Ne mets aucun markdown ni backtick."
    )
    user_msg = "Sujet: " + topic + "\n\nRedaction:\n" + essay

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.3,
        max_tokens=1500,
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
        note = data.get("note", "?/25")
        rc = data.get("respect_consigne", "?/5")
        org = data.get("organisation", "?/5")
        gram = data.get("grammaire", "?/5")
        voc = data.get("vocabulaire", "?/5")
        style = data.get("style", "?/5")
        points_forts = data.get("points_forts", [])
        erreurs = data.get("erreurs", [])
        vocab_rec = data.get("vocabulaire_recommande", [])

        result = "📊 Résultat DELF B2\n\n"
        result += "🏆 Note finale: " + note + "\n\n"
        result += "📋 Détail des notes\n"
        result += "- Respect de la consigne: " + rc + "\n"
        result += "- Organisation: " + org + "\n"
        result += "- Grammaire: " + gram + "\n"
        result += "- Vocabulaire: " + voc + "\n"
        result += "- Style: " + style + "\n\n"
        result += "✅ Points forts\n\n"
        for p in points_forts:
            result += "- " + p.strip() + "\n"
        result += "\n❌ Erreurs à corriger\n\n"
        for e in erreurs:
            result += "- " + e.strip() + "\n"
        result += "\n📚 Vocabulaire B2 recommandé\n\n"
        for v in vocab_rec:
            result += "- " + v.strip() + "\n"

        return result.strip()

    except Exception as e:
        print("Grade JSON Error: " + str(e))
        return clean_text(raw)


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
    return "Done! msg1=" + msg1[:80] + "...", 200


@app.route("/push", methods=["GET"])
def push():
    cache = load_daily()
    if cache:
        line_bot_api.broadcast(TextSendMessage(text=cache["message_1"]))
        return "Pushed! Check your LINE!", 200
    return "No content yet, run /generate first!", 400


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
        safe_reply(event.reply_token, "Envoie 完成 ou pour recevoir la redaction modele du jour!")


scheduler = BackgroundScheduler()
scheduler.add_job(morning_push, "cron", hour=8, minute=0)
scheduler.start()

if __name__ == "__main__":
    app.run(port=5000)
