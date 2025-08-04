from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse
from google.cloud import texttospeech
from google.oauth2 import service_account
from openai import OpenAI
import os
import json
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
import datetime

# טען את משתני הסביבה מהקובץ .env
load_dotenv()

# הגדרת מפתחות מהסביבה
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

# טען האישורים מהמשתנה
google_creds_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = service_account.Credentials.from_service_account_info(google_creds_dict)
client = texttospeech.TextToSpeechClient(credentials=credentials)

# הגדרת OpenAI client לפי גרסה 1+
client_gpt = OpenAI(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID,
    project=OPENAI_PROJECT_ID
)

app = Flask(__name__)

# אחסון מצב שיחה לפי session ID (לשימוש עתידי)
user_states = {}

# תפריט
menu_text = ""
def parse_menu():
    global menu_text
    tree = ET.parse("menu.xml")
    root = tree.getroot()
    text = f"תפריט עבור {root.attrib.get('store', '')}:"
    for category in root.findall('category'):
        text += f"\nקטגוריה: {category.attrib['name']}\n"
        for item in category.findall('item'):
            name = item.find('name').text
            price = item.find('price').text
            text += f"  {name} – {price} ₪\n"
            extras = item.find('extras')
            if extras is not None:
                for extra in extras.findall('extra'):
                    ename = extra.attrib['name']
                    eprice = extra.attrib['price']
                    text += f"    תוספת: {ename} – {eprice} ₪\n"
    menu_text = text

parse_menu()

# שיחה עם GPT
conversation_history = []
order_summary = ""
def ask_gpt(user_input):
    global order_summary
    if user_input == "התחלה":
        conversation_history.clear()

    if not conversation_history:
        conversation_history.append({"role": "system", "content": "אתה בוט להזמנות טלפוניות של פיצריה בשם פיצה שמש. אתה תמיד פונה בצורה אדיבה ומקצועית כאילו אתה נציג שירות אמיתי, ומנהל שיחה טבעית שלב אחר שלב. אתה פותח את השיחה במשפט 'שלום, הגעת לפיצה שמש – איך אפשר לעזור לך?' וממתין ללקוח. אל תציע מהתפריט מיוזמתך – תמיד רק לפי מה שהלקוח אומר. אתה שואל שלב־שלב: מה סוג הפיצה, איזה תוספות, כמות, שתייה או פסטה אם רלוונטי, ואז מסכם הכל כולל מחיר. אם המשתמש אומר 'פיצה חצי חצי עם זיתים וגבינה' – אתה מבין שמדובר על פיצה אחת, חצי זיתים חצי גבינה. אם הוא אומר '2 משפחתיות' – אתה מבין שמדובר על 2 פיצות נפרדות ושואל כל אחת בנפרד. אם המשתמש שותק – אתה מחכה ולא יוזם בעצמך. התפריט המלא הוא:\n" + menu_text})
        conversation_history.append({"role": "assistant", "content": "שלום, הגעת לפיצה שמש – איך אפשר לעזור לך?"})

    conversation_history.append({"role": "user", "content": user_input})
    chat_completion = client_gpt.chat.completions.create(
        model="gpt-4o",
        messages=conversation_history
    )
    reply = chat_completion.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": reply})

    if any(x in reply for x in ["סיכום הזמנה", "ההזמנה שלך", "סה\"כ", "לאשר"]):
        order_summary = reply
        save_order_summary(reply)

    return reply

def save_order_summary(summary):
    now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    with open(f"orders/order_{now}.txt", "w", encoding="utf-8") as f:
        f.write(summary)

# דיבור
def synthesize_speech(text):
    input_text = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Standard-A"
    )
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    with open("static/reply.mp3", "wb") as out:
        out.write(response.audio_content)

@app.route("/voice", methods=['POST'])
def voice():
    user_input = request.form.get("SpeechResult")

    if user_input:
        gpt_reply = ask_gpt(user_input)
        synthesize_speech(gpt_reply)
    else:
        gpt_reply = ask_gpt("התחלה")
        synthesize_speech(gpt_reply)

    twilio_response = VoiceResponse()
    gather = twilio_response.gather(
        input="speech",
        action="/voice",
        method="POST",
        timeout=5
    )
    gather.play("https://pizzabotvoice.onrender.com/static/reply.mp3")

    return str(twilio_response)

@app.route("/")
def index():
    return "Pizza Bot Voice is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
