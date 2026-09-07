# Mish AI Backend

Free & open-source backend that gives Mish the "real AI" voice conversation.
FastAPI that calls the free **Groq** tier (Llama 3.1 8B) for natural Roman Urdu
chat, with server-side mood analysis.

## Features
- `POST /ask` — chat endpoint used by the Android app
  - Input: `{ message, user_name, role, gender, detected_mood, energy }`
  - Output: `{ response, mood, tts_rate, tts_pitch }`
- Mood-aware answers (Happy/Sad/Angry/Stressed/Excited/Normal/Confused/Tired)
- Addresses the user by their name + role (boss/sir/madam/bhai/jani/jan/yar)
- Own personality: friendly + masti + Roman Urdu / Urdu
- Works **without any API key** too (local fallback replies so app always works)

## Setup (free)

1. Get a free key: https://console.groq.com/keys
2. Run locally:
   ```
   pip install -r requirements.txt
   $env:GROQ_API_KEY="gsk_..."   # PowerShell
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```
3. Test:
   ```
   curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" `
     -d '{"message":"Mish bas yar thak gaya hun","user_name":"Ali","role":"jani"}'
   ```

## Deploy free (no monthly cost)
- **Render free tier**: create a new Web Service, connect this repo,
  build command `pip install -r requirements.txt`,
  start command `uvicorn main:app --host 0.0.0.0 --port 8000`,
  add env var `GROQ_API_KEY`. You get `https://yourapp.onrender.com`.
- Your Android app endpoint = that URL (app calls `POST /ask`).

## Note
The app's `MishBackend` already calls `POST /ask` with the exact JSON above.
Set the backend URL once (e.g. via `PreferencesManager.setEndpoint`) and your
"Start Mish" button will deliver real AI female-voice chat.