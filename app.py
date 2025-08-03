from flask import Flask, request, Response
from twilio.twiml.voice_response import VoiceResponse
import os

app = Flask(__name__)

@app.route("/voice", methods=['GET', 'POST'])
def voice():
    """Respond to incoming calls with a simple greeting."""
    resp = VoiceResponse()
    resp.say("שלום וברוך הבא לפיצה שמש. איך אפשר לעזור לך?", language="he-IL", voice="Polly.Carmit")
    return Response(str(resp), mimetype='text/xml')  # חשוב מאוד להחזיר XML

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
