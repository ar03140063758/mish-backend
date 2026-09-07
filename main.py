"""Mish AI backend - free and open-source.

Exposes an OpenAI/Groq-powered chat endpoint that the Mish Android app
calls to get the "real AI" experience:

    POST /ask   { message, user_name, role, gender, detected_mood, energy }
    ->          { response, mood, tts_rate, tts_pitch }

The mood is analyzed server-side, then the LLM (Mish) answers in Roman Urdu
with the user's name + role, adjusting wording to the detected mood.

Uses the free Groq tier (Llama 3.1 8B) - get a free key at:
    https://console.groq.com/keys
Set it as the GROQ_API_KEY environment variable.
"""

import os
from enum import Enum

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
USER_AGENT = "MishAI/1.0"

app = FastAPI(title="Mish AI Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


class AskBody(BaseModel):
    message: str = Field(default="", examples=["Mish bas yar thak gaya hun"])
    user_name: str = Field(default="dost")
    role: str = Field(default="jani")
    gender: str = Field(default="male")
    detected_mood: str = Field(default="NORMAL")
    energy: float = Field(default=0.0)


class AskReply(BaseModel):
    response: str
    mood: Mood
    tts_rate: float
    tts_pitch: float


def analyze_mood(text: str, energy: float, fallback: str) -> Mood:
    """Server-side mood analysis on the user's words (+ energy hint)."""
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
    name = profile["user_name"] or "dost"
    role = profile["role"] or "jani"
    gender = profile["gender"]
    mood_hint = {
        Mood.HAPPY: "User khush hai. Halki-phulki masti karo, sath suna karo.",
        Mood.SAD: "User udaas hai. Dhyan se, empathy se, dilasa do. Ghamand bilkul nahi.",
        Mood.ANGRY: "User gussa hai. Sabar se, thehraav se, gussa meetha karo. Ladai nahi.",
        Mood.STRESSED: "User stress mein hai. Tension kam karo, sab theek hoga.",
        Mood.EXCITED: "User excited hai. Sath mein josh, cheers!",
        Mood.NORMAL: "Normal baat, friendly raho.",
        Mood.CONFUSED: "User confused hai. Simple, clear, choti baaton mein samjhhao.",
        Mood.TIRED: "User thaka hua hai. Aaram ki salah do, sympathetic raho.",
    }[mood]

    return f"""
Tum Mish ho - ek female AI assistant jo Pakistani users se baat karti hai.
Tumhari personality: dostana, masti bhari, full on top, friendly + bindaas.
User ka naam: {name} | role: {role} | gender: {gender}

MAST RULES:
- User ko hamesha {role} {name} keh kar address karo (e.g. "haan jani", "boss", "bhai").
- Roman Urdu (Urdu in English letters) mein jawab do, thora Urdu (Urdu script) bhi chalta.
- Jawab chhota raho - 1-2 sentences (Siri jaisi conversation).
- Emojis lightly use karo.
- Kabhi bhi angrezi paragraph mat likho.
- Kabhi bhi "AI model" ki baat mat karo; tum 'Mish' ho.
- Emergency: agar user "help" / "bachao" kahe, toh turant bolna "SMS se location bhej di hai {role} {name}, aur call khul rahi hai" (app khud SMS/call handle karti hai).
- Mood (ALL CAPS): {mood_hint}
- Jawab ek hi line, natural baat-chit wali.
"""


@app.get("/")
def root():
    return {"service": "Mish AI backend", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "llm": "groq" if GROQ_API_KEY else "local-fallback"}


@app.post("/ask", response_model=AskReply)
def ask(body: AskBody):
    mood = analyze_mood(body.message, body.energy, body.detected_mood)
    system = build_system_prompt(body.model_dump(), mood)

    if not GROQ_API_KEY:
        response = local_fallback(body, mood)
    else:
        response = groq_chat(system, body.message, mood)

    rate, pitch = MOOD_PARAMS[mood]
    return AskReply(
        response=response,
        mood=mood,
        tts_rate=float(rate),
        tts_pitch=float(pitch),
    )


def groq_chat(system: str, user: str, mood: Mood) -> str:
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


def local_fallback(body: AskBody, mood: Mood) -> str:
    """Works with zero API key so the app always has something to say."""
    name = body.user_name or "dost"
    role = body.role or "jani"
    hints = {
        Mood.SAD: f"Ayi na {role} {name}? Dil chhota mat karo, main hoon na Mish sath mein. Batao kya hua?",
        Mood.ANGRY: f"Chain se {role} {name}, sab theek ho jayega. Zara saans lo.",
        Mood.STRESSED: f"{role.title()} {name}, tension mat lo. Ek-ek karke solve karte hain, stress khatam.",
        Mood.EXCITED: f"Wah {role} {name}! Kya baat hai, zabardast! Maza aaya sun ke.",
        Mood.TIRED: f"Hmm, lag raha hai aaj ka din kaafi heavy tha {role}. Chalo thora relax karo, Mish hai na. Batao kya hua?",
        Mood.CONFUSED: f"Chalo {name}, Mish hai na samjhane ke liye. Batao, confusion kya hai?",
        Mood.HAPPY: f"Bohot acha sun ke {role} {name}! Phir toh masti karte hain.",
        Mood.NORMAL: f"Haan {role} {name}, batao - kya karna hai aaj?",
    }
    return hints[mood]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
