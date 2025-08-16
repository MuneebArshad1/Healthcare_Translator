from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
import uuid
from gtts import gTTS
from gtts.lang import tts_langs
from googletrans import Translator

app = FastAPI(title="Healthcare Translation API (Googletrans)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("temp", exist_ok=True)

translator = Translator()
GTTS_LANGS = tts_langs()

# Mapping for Googletrans language codes if different from gTTS
LANG_CODE_MAP = {
    "zh": "zh-cn",
    "pt": "pt",
    "he": "iw"  # Hebrew
}

def pick_tts_code(target_lang: str) -> Optional[str]:
    if target_lang in GTTS_LANGS:
        return target_lang
    if target_lang in LANG_CODE_MAP and LANG_CODE_MAP[target_lang] in GTTS_LANGS:
        return LANG_CODE_MAP[target_lang]
    return None

def map_to_google_code(lang_code: str) -> str:
    """Map gTTS code to Googletrans code if needed."""
    return LANG_CODE_MAP.get(lang_code, lang_code)

def compute_supported_targets() -> List[Dict[str, str]]:
    supported = []
    for code, name in GTTS_LANGS.items():
        supported.append({"code": code, "tts_code": code, "name": name})
    return sorted(supported, key=lambda x: x["code"])

SUPPORTED = compute_supported_targets()
SUPPORTED_CODES = {item["code"] for item in SUPPORTED}

class TranslateTTSRequest(BaseModel):
    text: str
    target_lang: str
    source_lang: Optional[str] = "auto"

@app.get("/")
def root():
    return {"message": "Healthcare Translation API (Googletrans) is running"}

@app.get("/languages")
def languages():
    return {"languages": SUPPORTED}

@app.post("/translate_tts")
def translate_tts(payload: TranslateTTSRequest):
    text = (payload.text or "").strip()
    target = payload.target_lang.strip().lower()
    source = (payload.source_lang or "auto").strip().lower()

    if not text:
        return JSONResponse({"error": "Text is empty."}, status_code=400)

    if target not in SUPPORTED_CODES:
        return JSONResponse({
            "error": f"Target language '{target}' not supported for TTS.",
            "hint": "Check /languages for supported codes."
        }, status_code=400)

    # Ensure codes are compatible with Googletrans
    google_target = map_to_google_code(target)
    google_source = None if source == "auto" else map_to_google_code(source)

    try:
        result = translator.translate(text, src=google_source or "auto", dest=google_target)
        translated_text = result.text
    except Exception as e:
        return JSONResponse({"error": f"Translation failed: {str(e)}"}, status_code=502)

    # TTS
    tts_code = pick_tts_code(target)
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
