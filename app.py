from flask import Flask, request
from twilio.twiml.voice_response import VoiceResponse
from google.cloud import texttospeech
from google.oauth2 import service_account
from openai import OpenAI
import os
import json
from dotenv import load_dotenv
import xml.etree.ElementTree as ET
from collections import defaultdict

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_ORG_ID = os.getenv("OPENAI_ORG_ID")
OPENAI_PROJECT_ID = os.getenv("OPENAI_PROJECT_ID")
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

# --- Google TTS Client ---
google_creds_dict = json.loads(GOOGLE_CREDS_JSON)
credentials = service_account.Credentials.from_service_account_info(google_creds_dict)
tts_client = texttospeech.TextToSpeechClient(credentials=credentials)

# --- OpenAI client ---
client_gpt = OpenAI(
    api_key=OPENAI_API_KEY,
    organization=OPENAI_ORG_ID,
    project=OPENAI_PROJECT_ID
)

app = Flask(__name__)

# יצירת תקיות נדרשות
os.makedirs("static", exist_ok=True)
os.makedirs("orders", exist_ok=True)

# =========================
#   טעינת תפריט מה-XML
# =========================

def load_menu_from_xml(path="menu.xml"):
    tree = ET.parse(path)
    root = tree.getroot()
    prices = {}
    extras_map = {}
    items = []

    for cat in root.findall("category"):
        for it in cat.findall("item"):
            name = it.find("name").text.strip()
            price = float(it.find("price").text.strip())
            prices[name] = price
            items.append(name)
            ex = it.find("extras")
            if ex is not None:
                extras_map[name] = [
                    (e.attrib["name"].strip(), float(e.attrib["price"].strip()))
                    for e in ex.findall("extra")
                ]

    return {
        "prices": prices,
        "extras_map": extras_map,
        "items": items,
        # רק הפריטים האלו מקבלים תוספות
        "items_with_extras": {
            "פיצה משפחתית",
            "פיצה אישית",
            "פיצה ללא גלוטן (אישי)",
        },
    }

MENU = load_menu_from_xml("menu.xml")

# =========================
#   בניית תקציר תפריט ל-GPT
# =========================

def build_menu_summary(menu: dict) -> str:
    lines = ["אל תשתמש בשום ידע חיצוני. רק מתוך הרשימה הזו."]
    # FIX: the original had an illegal newline string literal here
    lines.append("\nפריטים מותרים:")
    for name in menu["items"]:
        price = menu["prices"].get(name, 0)
        lines.append(f"- {name} — {price} ₪")
        if name in menu["extras_map"]:
            ex = ", ".join([f"{en}({int(ep)}₪)" for en, ep in menu["extras_map"][name]])
            lines.append(f"  תוספות: {ex}")
    # FIX: the original had an illegal string literal and wrong join token
    lines.append("\nרק שלושת הפריטים הבאים מקבלים תוספות: פיצה משפחתית, פיצה אישית, פיצה ללא גלוטן (אישי).")
    return "\n".join(lines)

MENU_SUMMARY = build_menu_summary(MENU)

# =========================
#     ניהול שיחה (State)
# =========================

sessions = defaultdict(lambda: {
    "state": "WELCOME",   # WELCOME→MODE→ORDER→EXTRAS→NAME→PHONE→ADDRESS→SUMMARY
    "mode": None,          # delivery / pickup
    "order": [],           # [{item:'שם פריט', extras:[], extras_done:bool}]
    "current_index": 0,
    "name": None,
    "phone": None,
    "address": None,
    "clarify": None,       # {"for_index":int, "keyword":str, "options":[...]}
})

# =========================
#   GPT: פענוח משפט חופשי
# =========================

def gpt_parse(user_text: str) -> dict:
    """
    מבקש מ-GPT להחזיר JSON עם פריטים/כמויות/תוספות/מצב (משלוח/איסוף)/שם/טלפון/כתובת.
    החזרה בפורמט צפוי, בלי לחרוג מהתפריט.
    """
    system = (
        "אתה מסייע בקבלת הזמנה טלפונית לפיצה שמש. החזר אך ורק JSON תקני. "
        "אל תמציא פריטים/תוספות שלא קיימים. אם משהו לא חוקי – התעלם ממנו."
    )

    # שים לב: זו מחרוזת רגילה (לא f-string) כדי שלא נתנגש עם סוגריים מסולסלים
    json_template = """{
  "items": [{"name": "שם פריט מדויק", "quantity": 1, "extras": []}],
  "mode": "delivery"|"pickup"|null,
  "name": null,
  "phone": null,
  "address": null
}"""

    user = f"""הטקסט של הלקוח:
{user_text}

עבוד לפי התפריט הבא בלבד:
{MENU_SUMMARY}

החזר JSON במבנה הבא בדיוק (אל תוסיף טקסט חוץ מה-JSON):
{json_template}

הערות:
- אל תציע כלום. רק תפענח את מה שנאמר. אם נאמרו כמויות – שים בשדה quantity.
- תוספות מותר רק ל"פיצה משפחתית" / "פיצה אישית" / "פיצה ללא גלוטן (אישי)" ורק מהקובץ.
- אם יש עמימות כמו "זיתים" כשיש סוגים שונים – אל תכריע; אל תוסיף extras.
"""

    resp = client_gpt.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
    )
    content = resp.choices[0].message.content.strip()
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

# =========================
#   עזר: תוספות + חצי/חצי
# =========================

def match_extra_ambiguity(keyword: str, legal_extras: list) -> list:
    options = []
    k = keyword.strip()
    for en, _ in legal_extras:
        if k in en:
            options.append(en)
    return options


def apply_extra_disambiguation(sess, user_text: str) -> bool:
    """כשיש הבהרה ממתינה (למשל זיתים ירוקים/שחורים), נקבע את התשובה ונמשיך."""
    if not sess.get("clarify"):
        return False
    c = sess["clarify"]
    idx = c["for_index"]
    text = (user_text or "").strip().lower()
    chosen = None
    for opt in c.get("options", []):
        lo = opt.lower()
        # מילות מפתח שיעזרו בבחירה
        tokens = ["ירוקים", "שחורים", "טריות", "רגילות"]
        if any(tok in text for tok in tokens) and any(tok in lo for tok in tokens):
            chosen = opt
            break
        if lo in text:
            chosen = opt
            break
    if chosen:
        sess["order"][idx]["extras"].append(chosen)
        sess["order"][idx]["extras_done"] = True
        sess["clarify"] = None
        return True
    return False


def interpret_extras_for_item_from_text(user_text: str, item_name: str):
    """מפענח תוספות לטקסט חופשי עבור פריט ספציפי, אך ורק מתוך ה-XML.
    מחזיר: (chosen_extras:list, done:bool, clarify:dict|None)
    """
    text = (user_text or "").strip().lower()
    legal = MENU["extras_map"].get(item_name, [])
    legal_names = [en for (en, _) in legal]

    # ללא תוספות
    if any(k in text for k in ["בלי כלום", "בלי", "ללא", "לא"]):
        return [], True, None

    chosen = []

    # זיהוי מדויק של שמות תוספת
    for en in legal_names:
        if en.lower() in text:
            chosen.append(en)

    # עמימות זיתים/פטריות
    clarify = None
    for kw in ["זיתים", "פטריות"]:
        if kw in text and not any(kw in c for c in chosen):
            opts = [en for (en, _) in legal if kw in en]
            if len(opts) > 1:
                clarify = {"keyword": kw, "options": opts}
                break
            elif len(opts) == 1:
                chosen.append(opts[0])

    # חצי/חצי – מבחינת חיוב זה שתי תוספות (כבר נספרות)
    # אין צורך בסימון מיוחד בקוד

    done = bool(chosen) and clarify is None
    return chosen, done, clarify

# =========================
#   מיזוג פלט GPT לשיחה
# =========================

def merge_parsed_into_session(sess, parsed: dict):
    # מצב משלוח/איסוף
    mode = parsed.get("mode")
    if mode in ("delivery", "pickup"):
        sess["mode"] = mode

    # שם/טלפון/כתובת
    if parsed.get("name"): sess["name"] = parsed["name"].strip()
    if parsed.get("phone"): sess["phone"] = ''.join(ch for ch in parsed["phone"] if ch.isdigit())
    if parsed.get("address"): sess["address"] = parsed["address"].strip()

    # פריטים
    items = parsed.get("items") or []
    for it in items:
        name = it.get("name")
        qty = int(it.get("quantity") or 1)
        extras = it.get("extras") or []
        if name in MENU["prices"]:
            for _ in range(max(1, qty)):
                entry = {"item": name, "extras": [], "extras_done": False}
                if name in MENU["items_with_extras"] and name in MENU["extras_map"]:
                    legal = {en for (en, _) in MENU["extras_map"][name]}
                    valids = [e for e in extras if e in legal]
                    if valids:
                        entry["extras"].extend(valids)
                        entry["extras_done"] = True
                else:
                    entry["extras_done"] = True
                sess["order"].append(entry)

    # אם נוספו פריטים שמקבלים תוספות ללא פירוט – נעבור לשלב EXTRAS
    for i, p in enumerate(sess["order"]):
        if p["item"] in MENU["items_with_extras"] and not p["extras_done"]:
            sess["state"] = "EXTRAS"
            sess["current_index"] = i
            return

# =========================
#   השאלה הבאה לפי מצב
# =========================

def next_question(sess):
    if sess.get("clarify"):
        c = sess["clarify"]
        if c.get("keyword") == "זיתים":
            return "תרצה זיתים ירוקים או זיתים שחורים?"
        if c.get("keyword") == "פטריות":
            if any("טריות" in o for o in c.get("options", [])):
                return "רצית פטריות רגילות או פטריות טריות?"
            return "רצית פטריות? אם לא, אפשר להגיד 'בלי כלום'."
        return "איזו תוספת בדיוק תרצה?"

    s = sess["state"]

    if s == "WELCOME":
        sess["state"] = "MODE"
        return "שלום! תודה שהתקשרת לפיצה שמש – מדבר ליאם. איך אפשר לעזור?"

    if s == "MODE":
        if not sess["mode"]:
            return "זה יהיה במשלוח או באיסוף?"
        sess["state"] = "ORDER"
        return "אפשר להגיד את ההזמנה שלך."

    if s == "ORDER":
        if sess["order"]:
            sess["state"] = "EXTRAS"
        else:
            return "מה תרצה להזמין?"

    if s == "EXTRAS":
        cur = sess["order"][sess["current_index"]]
        item_name = cur["item"]
        if item_name not in MENU["items_with_extras"] or cur["extras_done"]:
            if sess["current_index"] < len(sess["order"]) - 1:
                sess["current_index"] += 1
                nxt = sess["order"][sess["current_index"]]["item"]
                return f"נעבור לפריט הבא: {nxt}. תרצה תוספות או להשאיר בלי?"
            sess["state"] = "NAME"
            return "איך אפשר לרשום את השם?"
        else:
            legal = [en for (en, _) in MENU["extras_map"].get(item_name, [])]
            return f"ל{item_name}, תרצה להוסיף תוספות? אפשר להגיד 'בלי כלום', או לבחור מתוך: {', '.join(legal[:6])}…"

    if s == "NAME":
        if not sess.get("name"):
            return "איך אפשר לרשום את השם?"
        sess["state"] = "PHONE"
        return "ומה מספר הטלפון שלך?"

    if s == "PHONE":
        if not sess.get("phone"):
            return "אפשר את מספר הטלפון?"
        if sess["mode"] == "delivery":
            sess["state"] = "ADDRESS"
            return "מה הכתובת המלאה למשלוח?"
        sess["state"] = "SUMMARY"
        return "אני מסכם את ההזמנה שלך…"

    if s == "ADDRESS":
        if not sess.get("address"):
            return "מה הכתובת המלאה למשלוח?"
        sess["state"] = "SUMMARY"
        return "תודה! מסכם את ההזמנה…"

    if s == "SUMMARY":
        return "רגע קטן ואני מסכם…"

    return "איך אפשר לעזור?"

# =========================
#      חישוב עלויות
# =========================

def compute_total(sess):
    total = 0.0
    lines = []
    for p in sess["order"]:
        item_name = p["item"]
        base = MENU["prices"].get(item_name, 0)
        ex_sum = 0.0
        for ex in p["extras"]:
            for (en, ep) in MENU["extras_map"].get(item_name, []):
                if ex == en:
                    ex_sum += ep
                    break
        subtotal = base + ex_sum
        total += subtotal
        ex_txt = ", ".join(p["extras"]) if p["extras"] else "בלי תוספות"
        lines.append(f"{item_name} – {ex_txt} ({subtotal:.0f} ₪)")
    return total, lines

# =========================
#          TTS
# =========================

def tts(text: str, path="static/reply.mp3"):
    input_text = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code="he-IL", name="he-IL-Wavenet-A")
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    response = tts_client.synthesize_speech(input=input_text, voice=voice, audio_config=audio_config)
    with open(path, "wb") as out:
        out.write(response.audio_content)

# =========================
#        Webhook Twilio
# =========================

@app.route("/voice", methods=['POST'])
def voice():
    try:
        call_sid = request.form.get("CallSid") or request.form.get("From") or "anon"
        sess = sessions[call_sid]
        user_text = (request.form.get("SpeechResult") or "").strip()

        # 1) הבהרת תוספת אם ממתינה
        if user_text and sess.get("clarify"):
            if apply_extra_disambiguation(sess, user_text):
                pass  # ההבהרה טופלה

        # 2) פענוח חופשי עם GPT בכל תשובה
        if user_text:
            parsed = gpt_parse(user_text)
            if parsed:
                merge_parsed_into_session(sess, parsed)

        # 3) אם אנחנו בשלב תוספות – ננסה לפרש תוספות עבור הפריט הנוכחי
        if sess["state"] == "EXTRAS" and sess["order"]:
            idx = sess["current_index"]
            cur = sess["order"][idx]
            item_name = cur["item"]
            if item_name in MENU["items_with_extras"]:
                chosen, done, clarify = interpret_extras_for_item_from_text(user_text, item_name)
                if clarify and not done:
                    sess["clarify"] = {"for_index": idx, **clarify}
                elif done:
                    for ex in chosen:
                        if ex not in cur["extras"]:
                            cur["extras"].append(ex)
                    cur["extras_done"] = True

        # 4) אם יש עדיין פריט שמחכה לתוספות – ודא שאנחנו עליו
        for i, p in enumerate(sess["order"]):
            if p["item"] in MENU["items_with_extras"] and not p["extras_done"]:
                sess["state"] = "EXTRAS"
                sess["current_index"] = i
                break
        else:
            # אם אין עוד תוספות לחכות להן והזמנה קיימת – התקדם לפרטים
            if sess["order"] and sess["state"] in ("ORDER", "EXTRAS"):
                sess["state"] = "NAME"

        # 5) אם הגענו לסיכום – נסכם ונבקש אישור
        if sess["state"] == "SUMMARY":
            total, lines = compute_total(sess)
            tail = []
            if sess.get("name"): tail.append(f"שם: {sess['name']}")
            if sess.get("phone"): tail.append(f"טלפון: {sess['phone']}")
            if sess["mode"] == "delivery" and sess.get("address"): tail.append(f"כתובת: {sess['address']}")
            summary = "אז לסיכום: " + "; ".join(lines)
            if tail:
                summary += ". " + "; ".join(tail)
            summary += f". סך הכול {total:.0f} שקלים. האם זה בסדר ואפשר להעביר להכנה?"
            tts(summary)
            tw = VoiceResponse()
            g = tw.gather(input="speech", action="/voice", method="POST", timeout=10, speech_timeout="auto", language="he-IL")
            g.play("https://pizzabotvoice.onrender.com/static/reply.mp3")
            return str(tw)

        # 6) אחרת – השאלה הבאה לפי מצב
        question = next_question(sess)
        tts(question)
        tw = VoiceResponse()
        g = tw.gather(input="speech", action="/voice", method="POST", timeout=9, speech_timeout="auto", language="he-IL")
        g.play("https://pizzabotvoice.onrender.com/static/reply.mp3")
        return str(tw)

    except Exception:
        fallback = VoiceResponse()
        fallback.say("הייתה בעיית קליטה רגעית. אפשר לחזור על מה שאמרת?", language="he-IL", voice="Polly.Michael")
        fallback.gather(input="speech", action="/voice", method="POST", timeout=8, speech_timeout="auto", language="he-IL")
        return str(fallback)

@app.route("/")
def index():
    return "Pizza Bot Voice is running!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
