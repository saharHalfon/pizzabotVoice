from flask import Flask, request, send_file
from twilio.twiml.voice_response import VoiceResponse
from google.cloud import texttospeech
from google.api_core.client_options import ClientOptions
import os

app = Flask(__name__)

# שמור את מפתח ה-API שלך מהסביבה
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "AIzaSyBE7Cw8BUKUhxmkANdDzFPu1lQRQNRKDSA")

# יצירת לקוח Google Text-to-Speech
client = texttospeech.TextToSpeechClient(client_options=ClientOptions(api_key=GOOGLE_API_KEY))

@app.route("/voice", methods=['POST'])
def voice():
    # הטקסט שייאמר
    text = "שלום וברוך הבא לפיצה שמש. איך אפשר לעזור לך היום?"

    # הגדרת הטקסט
    input_text = texttospeech.SynthesisInput(text=text)

    # בחירת קול בעברית
    voice = texttospeech.VoiceSelectionParams(
        language_code="he-IL",
        name="he-IL-Standard-A"
    )

    # פורמט MP3
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    # בקשת יצירת קול
    response = client.synthesize_speech(
        input=input_text,
        voice=voice,
        audio_config=audio_config
    )

    # שמירת הקול לקובץ
    with open("static/welcome.mp3", "wb") as out:
        out.write(response.audio_content)

    # תגובת Twilio: משמיע את הקובץ
    twilio_response = VoiceResponse()
    twilio_response.play("https://pizzabotvoice.onrender.com/static/welcome.mp3")

    return str(twilio_response)

@app.route("/")
def index():
    return "Pizza Bot Voice is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)