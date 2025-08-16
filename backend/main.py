from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
import uuid
import tempfile
import requests
from dotenv import load_dotenv
from gtts import gTTS
from gtts.lang import tts_langs
from openai import OpenAI

# ========= Setup =========
load_dotenv()

TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
API_URL = "https://api.together.xyz/v1/chat/completions"
MODEL_NAME = "mistralai/Mixtral-8x7B-Instruct-v0.1"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # required for /transcribe

if not TOGETHER_API_KEY:
    print("WARNING: TOGETHER_API_KEY not set in .env file")
if not OPENAI_API_KEY:
    print("WARNING: OPENAI_API_KEY not set. /transcribe will fail")

# ✅ OpenAI client for Whisper
client = OpenAI()

app = FastAPI(title="Healthcare Translation API (Mixtral + Whisper via Together API)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("temp", exist_ok=True)

GTTS_LANGS = tts_langs()

LANG_CODE_MAP = {
    "zh": "zh-CN",
    "pt": "pt",
    "he": "iw",
}

def pick_tts_code(target_lang: str) -> Optional[str]:
    if target_lang in GTTS_LANGS:
        return target_lang
    mapped = LANG_CODE_MAP.get(target_lang)
    if mapped and mapped in GTTS_LANGS:
        return mapped
    return None

def compute_supported_targets() -> List[Dict[str, str]]:
    supported = [{"code": code, "tts_code": code, "name": name}
                 for code, name in GTTS_LANGS.items()]
    supported.sort(key=lambda x: x["code"])
    return supported

SUPPORTED = compute_supported_targets()
SUPPORTED_CODES = {item["code"] for item in SUPPORTED}

class TranslateTTSRequest(BaseModel):
    text: str
    target_lang: str
    source_lang: Optional[str] = "auto"

def code_to_lang_name(code: str) -> str:
    if code in GTTS_LANGS:
        return GTTS_LANGS[code]
    mapped = LANG_CODE_MAP.get(code)
    if mapped and mapped in GTTS_LANGS:
        return GTTS_LANGS[mapped]
    return code

def mistral_translate_together(text: str, target_code: str, source_code: Optional[str] = "auto") -> str:
    if not TOGETHER_API_KEY:
        raise RuntimeError("Missing TOGETHER_API_KEY")

    target_name = code_to_lang_name(target_code)
    src_desc = "auto-detect the source language accurately" if source_code in (None, "", "auto") \
               else f"the source language is '{code_to_lang_name(source_code)}'"

    prompt = (
        f"You are a professional medical translator.\n"
        f"Task: Translate the given text into **{target_name}**.\n"
        f"- Detect and handle medical terminology precisely.\n"
        f"- Preserve meaning, tone, and clinical nuance.\n"
        f"- {src_desc}.\n"
        f"- Output ONLY the translated text, no extra words.\n\n"
        f"Text:\n'''{text}'''"
    )

    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a highly skilled professional medical translator."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 400,
        "temperature": 0.2,
    }

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"Together API error {resp.status_code}: {resp.text}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError):
        raise RuntimeError("Invalid response from Together API")

@app.get("/")
def root():
    return {"message": "Healthcare Translation API (Mixtral + Whisper via Together API) is running"}

@app.get("/languages")
def languages():
    return {"languages": SUPPORTED}

@app.post("/translate_tts")
def translate_tts(payload: TranslateTTSRequest):
    text = (payload.text or "").strip()
    target = (payload.target_lang or "").strip()
    source = (payload.source_lang or "auto").strip().lower()

    if not text:
        return JSONResponse({"error": "Text is empty."}, status_code=400)

    if target not in SUPPORTED_CODES:
        return JSONResponse({
            "error": f"Target language '{target}' not supported for TTS.",
            "hint": "Use GET /languages for supported codes."
        }, status_code=400)

    try:
        translated_text = mistral_translate_together(text, target, source)
        if not translated_text:
            raise RuntimeError("Empty translation")
    except Exception as e:
        return JSONResponse({"error": f"Translation failed: {e}"}, status_code=502)

    tts_code = pick_tts_code(target)
    if not tts_code:
        return JSONResponse({
            "error": f"No TTS voice available for '{target}'."
        }, status_code=400)

    try:
        filename = f"{uuid.uuid4()}.mp3"
        out_path = os.path.join("temp", filename)
        gTTS(text=translated_text, lang=tts_code).save(out_path)
    except Exception as e:
        return JSONResponse({"error": f"TTS failed: {e}"}, status_code=502)

    return {
        "original_text": text,
        "translated_text": translated_text,
        "target_lang": target,
        "audio_url": f"/get_audio/{filename}"
    }

@app.get("/get_audio/{filename}")
def get_audio(filename: str):
    file_path = os.path.join("temp", filename)
    if not os.path.exists(file_path):
        return JSONResponse({"error": "File not found."}, status_code=404)
    return FileResponse(file_path, media_type="audio/mpeg")

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
    if not OPENAI_API_KEY:
        return JSONResponse({"error": "Missing OPENAI_API_KEY"}, status_code=500)

    content = await file.read()
    suffix = os.path.splitext(file.filename or "")[1] or ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )
        text = resp.text if hasattr(resp, "text") else str(resp)
    except Exception as e:
        os.remove(tmp_path)
        return JSONResponse({"error": f"Transcription failed: {e}"}, status_code=502)

    os.remove(tmp_path)
    return {"text": text}
