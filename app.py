from flask import Flask, request, redirect
from twilio.twiml.voice_response import VoiceResponse

app = Flask(__name__)

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    """Respond to incoming calls with a simple greeting."""
    resp = VoiceResponse()
    resp.say("שלום וברוך הבא לפיצה שמש. איך אפשר לעזור לך?", language="he-IL", voice="Polly.Carmit")
    return str(resp)

if __name__ == "__main__":
    app.run(debug=True)
