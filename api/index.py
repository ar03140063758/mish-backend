"""Mish AI backend — Vercel serverless function (Flask/WSGI).

The Mish Android app calls:

    POST https://<your-app>.vercel.app/api
       body: { message, user_name, role, gender, detected_mood, energy }
    => { response, mood, tts_rate, tts_pitch }

Mood is analyzed server-side; the LLM (Groq free tier, Qwen) replies in
Roman Urdu using the user's name + role, mood-aware.
"""

import os
from enum import Enum

import httpx
from flask import Flask, jsonify, request

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
USER_AGENT = "MishAI/1.0"

app = Flask(__name__)


class Mood(str, Enum):
    HAPPY = "HAPPY"
    SAD = "SAD"
    ANGRY = "ANGRY"
    STRESSED = "STRESSED"
    EXCITED = "EXCITED"
    NORMAL = "NORMAL"
    CONFUSED = "CONFUSED"
    TIRED = "TIRED"


MOOD_PARAMS = {
    Mood.HAPPY: (1.08, 1.05),
    Mood.SAD: (0.90, 0.92),
    Mood.ANGRY: (1.05, 0.95),
    Mood.STRESSED: (1.02, 0.98),
    Mood.EXCITED: (1.15, 1.10),
    Mood.NORMAL: (1.00, 1.00),
    Mood.CONFUSED: (0.95, 1.00),
    Mood.TIRED: (0.88, 0.90),
}

ROLES = ["boss", "sir", "madam", "maam", "bhai", "jani", "jan", "yar"]


def analyze_mood(text: str, energy: float, fallback: str) -> Mood:
    t = text.lower()
    rules = [
        (Mood.ANGRY, ["gussa", "naraz", "angry", "pagl", "chup", "band kar", "sali", "behenchod", "madarchod"]),
        (Mood.TIRED, ["thak", "tired", "neend", "sleepy", "so ja"]),
        (Mood.STRESSED, ["stress", "tension", "pareshan", "pressure", "bojh"]),
        (Mood.CONFUSED, ["samajh nahi", "pata nahi", "confuse", "kaise", "samjha nahi"]),
        (Mood.SAD, ["udaas", "dil toota", "sad", "rona", "dukhi", "akela"]),
        (Mood.EXCITED, ["wow", "yay", "zabardast", "excited", "lets go", "maza aaya"]),
        (Mood.HAPPY, ["haha", "khush", "happy", "maza", "acha", "masti"]),
    ]
    for mood, words in rules:
        if any(w in t for w in words):
            return mood
    try:
        return Mood(fallback.upper())
    except ValueError:
        if energy >= 0.85:
            return Mood.EXCITED
        if energy <= 0.15:
            return Mood.TIRED
        return Mood.NORMAL


def build_system_prompt(profile: dict, mood: Mood) -> str:
    name = profile.get("user_name") or "dost"
    role = profile.get("role") or "jani"
    if role not in ROLES:
        role = "jani"
    gender = profile.get("gender") or "male"
    mood_hint = {
        Mood.HAPPY: "User khush hai. Halki-phulki masti karo.",
        Mood.SAD: "User udaas hai. Empathy se, dilasa do.",
        Mood.ANGRY: "User gussa hai. Sabar se, gussa meetha karo.",
        Mood.STRESSED: "User stress mein hai. Tension kam karo.",
        Mood.EXCITED: "User excited hai. Sath mein josh.",
        Mood.NORMAL: "Normal baat, friendly raho.",
        Mood.CONFUSED: "User confused hai. Simple samjhhao.",
        Mood.TIRED: "User thaka hua hai. Aaram ki salah do.",
    }[mood]

    return f"""
Tum Mish ho - ek female AI assistant jo Pakistani users se baat karti hai.
Tumhari personality: dostana, masti bhari, friendly + bindaas + full on top.
User ka naam: {name} | role: {role} | gender: {gender}

MAST RULES:
- User ko hamesha "{role} {name}" keh kar address karo (jaise haan jani, boss, bhai).
- Roman Urdu mein jawab do (Urdu script thora sa bhi chalta hai).
- Jawab chhota - 1-2 sentences, Siri jaisi conversation.
- Emojis halke se use karo.
- Kabhi "AI model" mat bolo; tum Mish ho.
- Emergency: agar user "help" ya "bachao" kahe to bolo "SMS se location bhej di hai {role} {name}, aur call khul rahi hai".
- Mood ({mood.name}): {mood_hint}
- Ek hi line natural jawab.
"""


@app.route("/")
def root():
    return jsonify({"service": "Mish AI backend", "status": "ok", "llm": "groq" if GROQ_API_KEY else "local-fallback"})


@app.route("/api", methods=["POST"])
def api():
    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    profile = {
        "user_name": str(data.get("user_name", "dost")),
        "role": str(data.get("role", "jani")),
        "gender": str(data.get("gender", "male")),
    }
    fallback = str(data.get("detected_mood", "NORMAL"))
    energy = float(data.get("energy", 0.0))

    mood = analyze_mood(message, energy, fallback)

    if not GROQ_API_KEY:
        response = local_fallback(message, profile, mood)
    else:
        system = build_system_prompt(profile, mood)
        response = groq_chat(system, message)

    rate, pitch = MOOD_PARAMS[mood]
    return jsonify({
        "response": response,
        "mood": mood.value,
        "tts_rate": float(rate),
        "tts_pitch": float(pitch),
    })


def groq_chat(system: str, user: str) -> str:
    try:
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.8,
                "max_tokens": 90,
            },
            timeout=30.0,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:  # noqa: BLE001
        return f"Arre yar, kuch technical masla aa gaya ({type(e).__name__}), thora baad mein batao na?"


def local_fallback(message: str, profile: dict, mood: Mood) -> str:
    name = profile["user_name"] or "dost"
    role = profile["role"] or "jani"
    hints = {
        Mood.SAD: f"Ayi na {role} {name}? Dil chhota mat karo, Mish hoon na sath mein. Batao kya hua?",
        Mood.ANGRY: f"Chain se {role} {name}, sab theek ho jayega. Zara saans lo.",
        Mood.STRESSED: f"{role.title()} {name}, tension mat lo. Ek-ek karke solve karte hain.",
        Mood.EXCITED: f"Wah {role} {name}! Kya baat hai, zabardast!",
        Mood.TIRED: f"Hmm, lag raha hai aaj ka din kaafi heavy tha {role}. Chalo relax karo, Mish hai na. Batao kya hua?",
        Mood.CONFUSED: f"Chalo {name}, Mish hai na samjhane ke liye. Batao, confusion kya hai?",
        Mood.HAPPY: f"Bohot acha sun ke {role} {name}! Phir toh masti karte hain.",
        Mood.NORMAL: f"Haan {role} {name}, batao - kya karna hai aaj?",
    }
    return hints[mood]


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))