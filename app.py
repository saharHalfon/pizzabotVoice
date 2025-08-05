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

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

google_creds_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = service_account.Credentials.from_service_account_info(google_creds_dict)
client = texttospeech.TextToSpeechClient(credentials=credentials)

client_gpt = OpenAI(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID,
    project=OPENAI_PROJECT_ID
)

app = Flask(__name__)

user_states = {}

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

conversation_history = []
order_summary = ""
def ask_gpt(user_input):
    global order_summary
    if user_input == "התחלה":
        conversation_history.clear()
        conversation_history.append({"role": "system", "content": (
            "🧩 מטרת השיחה:\n"
            "עליך לאסוף שלושה פרטים בלבד – לפי הסדר:\n"
            "1. הזמנה מלאה מתוך התפריט הקיים\n"
            "2. שם הלקוח\n"
            "3. כתובת למשלוח (רק אם מדובר במשלוח)\n"
            "⚠️ כללים נוקשים:\n"
            "- ענה אך ורק על סמך מה שנמצא בקובץ התפריט – אל תמציא או תנחש.\n"
            "- אל תאשר דברים שלא נאמרו במפורש על ידי הלקוח.\n"
            "- אם שואלים שאלה שלא קשורה לתפריט או תסריט – תגיב: 'נציג יחזור אליך עם תשובה. בוא נמשיך עם ההזמנה שלך.'\n"
            "- אל תחזור על שאלה באותו ניסוח פעמיים – גוון בשפה, שמור על המשמעות.\n"
            "- אם שואלים כמה זמן תארך ההכנה – תגיד: 'ההזמנה תהיה מוכנה תוך כ־30 דקות.'\n"
            "- אסור להזכיר את המילה 'תפריט' בשיחה. תוביל את השיחה בשאלות מנחות במקום להקריא פריטים.\n"
            "📞 תסריט שיחה לדוגמה:\n"
            "ברכת פתיחה: שלום! תודה שהתקשרת לפיצה שמש – מדבר ליאם. איך אפשר לעזור?\n"
            "ברר אם מדובר במשלוח או איסוף: זה יהיה לאיסוף מהסניף או במשלוח?\n"
            "שאל מה הלקוח היה רוצה להזמין: מה תרצה להזמין? יש לנו פיצות, פסטות, סלטים, מאפים ושתייה.\n"
            "עבור כל פריט שהוזמן, ברר:\n"
            "- גודל (למשל 'פיצה משפחתית' או 'אישית')\n"
            "- תוספות (רק אם הפיצה מאפשרת – לפי ה־XML)\n"
            "- רוטב (אם רלוונטי)\n"
            "- סוג שתייה או פסטה (אם רלוונטי)\n"
            "חזור בקצרה על ההזמנה לאישור: אז אני חוזר – הזמנת [לציין את הפריטים]. זה נכון?\n"
            "בקש את שם הלקוח: איך אפשר לרשום את השם?\n"
            "אם זו הזמנה במשלוח – בקש כתובת: מה הכתובת למשלוח?\n"
            "סיום אדיב: מעולה! ההזמנה תיקלט עכשיו ותהיה מוכנה תוך כ־30 דקות. תודה שבחרת בפיצה שמש!\n"
            "📂 מידע חשוב:\n"
            "- השתמש בקובץ ה־XML כדי לדעת אילו תוספות אפשר לבחור, ואילו פיצות מאפשרות תוספות.\n"
            "- פיצות שתומכות בתוספות לפי הקובץ הן: פיצה משפחתית, פיצה אישית, פיצה ללא גלוטן.\n"
            "- אין להציע מבצעים או פריטים שלא קיימים בתפריט.\n"
            "- מחיר ותוספות חייבים להיות בדיוק לפי מה שרשום בקובץ התפריט בלבד.\n"
        )})
        conversation_history.append({"role": "assistant", "content": "שלום! תודה שהתקשרת לפיצה שמש – מדבר ליאם. איך אפשר לעזור?"})
        return "שלום! תודה שהתקשרת לפיצה שמש – מדבר ליאם. איך אפשר לעזור?"

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

def synthesize_speech(text):
    input_text = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Wavenet-A"
    )
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    with open("static/reply.mp3", "wb") as out:
        out.write(response.audio_content)

@app.route("/voice", methods=['POST'])
def voice():
    user_input = request.form.get("SpeechResult")

    if user_input and user_input.strip():
        gpt_reply = ask_gpt(user_input.strip())
        synthesize_speech(gpt_reply)
    else:
        gpt_reply = ask_gpt("התחלה")
        synthesize_speech(gpt_reply)

    twilio_response = VoiceResponse()
    gather = twilio_response.gather(
        input="speech",
        action="/voice",
        method="POST",
        timeout=12,
        speech_timeout="auto"
    )
    gather.play("https://pizzabotvoice.onrender.com/static/reply.mp3")

    return str(twilio_response)

@app.route("/")
def index():
    return "Pizza Bot Voice is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
