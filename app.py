import google.generativeai as genai
import json, os, re
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import date

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

line_bot_api = LineBotApi(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.environ.get("LINE_CHANNEL_SECRET"))
app = Flask(__name__)

CACHE_FILE = "daily_cache.json"

def save_daily(msg1, msg2):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "date": str(date.today()),
            "message_1": msg1,
            "message_2": msg2
        }, f, ensure_ascii=False)

def load_daily():
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

user_states = {}

def generate_delf_practice():
    today = date.today().strftime("%d %B %Y")
    prompt = f"""Tu es un coach DELF B2. Aujourd'hui, nous sommes le {today}.

Génère en JSON uniquement (sans markdown) :
{{
  "message_1": "📝 Sujet DELF B2 du jour\\n\\n[sujet]\\n\\n📚 Vocabulaire B2 essentiel\\n🔹 Verbes: [5 verbes]\\n🔹 Noms: [5 noms]\\n🔹 Adverbes: [5 adverbes]\\n🔹 Expressions: [5 expressions]",
  "message_2": "✍️ Rédaction modèle\\n\\n[rédaction minimum 250 mots]"
}}"""
    try:
        response = model.generate_content(prompt)
        raw = re.sub(r"```json|```", "", response.text).strip()
        data = json.loads(raw)
        return data["message_1"], data["messag
