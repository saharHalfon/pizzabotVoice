from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
import openai
import os
from dotenv import load_dotenv
import xml.etree.ElementTree as ET

# טען את משתני הסביבה מהקובץ .env
load_dotenv()

# הגדרת מפתחות מהסביבה
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")

# הגדרת לקוחות
client = texttospeech.TextToSpeechClient(client_options=ClientOptions(api_key=GOOGLE_API_KEY))
openai.api_key = OPENAI_API_KEY
openai.organization = OPENAI_ORG_ID
openai.project = OPENAI_PROJECT_ID

app = Flask(__name__)


def parse_menu():
    tree = ET.parse("menu.xml")
    root = tree.getroot()
    text = f"תפריט עבור {root.attrib.get('store', '')}:\n"
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
    return text

def ask_gpt(menu_text, user_input):
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": f"אתה בוט להזמנות טלפוניות של פיצריה. התפריט הוא:\n{menu_text}"},
            {"role": "user", "content": user_input}
        ]
    )
    return response['choices'][0]['message']['content']

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
    user_input = "אני רוצה פיצה משפחתית עם תוספת פטריות"
    menu_text = parse_menu()
    gpt_reply = ask_gpt(menu_text, user_input)
    synthesize_speech(gpt_reply)

    twilio_response = VoiceResponse()
    twilio_response.play("https://pizzabotvoice.onrender.com/static/reply.mp3")
    return str(twilio_response)

@app.route("/")
def index():
    return "Pizza Bot Voice is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
