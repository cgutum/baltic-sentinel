"""ElevenLabs voice generation — Person B.

Turns a watch-officer ``voice_script`` into a spoken MP3 briefing via ElevenLabs TTS.

Real audio only: if there is no API key, the SDK is missing, or the call fails, this
returns ``audio_generated=False`` with a reason and writes NO file — the caller (and
the UI) then fall back to on-device speech. We never fabricate audio.

Generated clips land in ``demo_assets/voice/<suspicion_id>.mp3`` and are served by
``GET /voice/audio/{suspicion_id}`` (see api/routes.py).
"""

import threading
from pathlib import Path

from ..config import settings

# Generated briefings live beside the demo assets, one file per suspicion.
_VOICE_DIR = Path(__file__).resolve().parents[3] / "demo_assets" / "voice"

# Retry count for transient ElevenLabs failures (429/5xx/empty stream).
_MAX_ATTEMPTS = 2

# Hard cap on characters sent to ElevenLabs per briefing. ElevenLabs bills per
# character, so this bounds credit burn even if a verdict produces a long script.
# A watch-officer alert is only 1-3 sentences anyway. Trimmed at a sentence boundary.
_MAX_CHARS = 600


def _cap(script: str) -> str:
    if len(script) <= _MAX_CHARS:
        return script
    cut = script[:_MAX_CHARS]
    boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:boundary + 1] if boundary > 120 else cut).strip()

_client = None
_client_lock = threading.Lock()


def is_configured() -> bool:
    """True when a real ElevenLabs key is present (not blank / not the placeholder)."""
    key = (settings.elevenlabs_api_key or "").strip()
    return bool(key) and not key.lower().startswith("your_")


def _get_client():
    """Lazily build a shared ElevenLabs client (import deferred so the backend boots
    even when the SDK isn't installed)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                from elevenlabs.client import ElevenLabs
                _client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    return _client


def audio_path(suspicion_id: str) -> Path:
    """Where the MP3 for a given suspicion lives. Filename is sanitised."""
    safe = "".join(c for c in str(suspicion_id) if c.isalnum() or c in "-_") or "latest"
    return _VOICE_DIR / f"{safe}.mp3"


def synthesize(voice_script: str, suspicion_id: str) -> dict:
    """Generate an MP3 of ``voice_script`` with ElevenLabs and write it to disk.

    Returns ``{voice_path, audio_generated, error?}``. On any failure (no key, no
    SDK, network/API error, empty output) ``audio_generated`` is False, ``voice_path``
    is None, and the UI falls back to on-device speech — no faked audio.
    """
    script = (voice_script or "").strip()
    if not script:
        return {"voice_path": None, "audio_generated": False, "error": "empty voice script"}
    if not is_configured():
        return {"voice_path": None, "audio_generated": False,
                "error": "ELEVENLABS_API_KEY not set"}
    script = _cap(script)  # bound per-briefing credit cost

    # Try a couple of times: ElevenLabs can return a transient 429/5xx, and a single
    # blip should never leave a vessel without its briefing.
    last_err = "unknown error"
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            client = _get_client()
            audio = client.text_to_speech.convert(
                voice_id=settings.elevenlabs_voice_id,
                model_id=settings.elevenlabs_model_id,
                text=script,
                output_format="mp3_44100_128",
            )
            _VOICE_DIR.mkdir(parents=True, exist_ok=True)
            out = audio_path(suspicion_id)
            with open(out, "wb") as fh:
                for chunk in audio:
                    if chunk:
                        fh.write(chunk)
            size = out.stat().st_size if out.exists() else 0
            if size == 0:
                out.unlink(missing_ok=True)
                last_err = "empty audio stream"
                print(f"[voice] attempt {attempt}/{_MAX_ATTEMPTS}: empty audio stream")
                continue
            print(f"[voice] ElevenLabs briefing -> {out} ({size} bytes, "
                  f"voice={settings.elevenlabs_voice_id}, attempt {attempt})")
            return {"voice_path": str(out), "audio_generated": True}
        except Exception as e:  # noqa: BLE001 — never let TTS break an investigation
            last_err = str(e)[:200]
            print(f"[voice] attempt {attempt}/{_MAX_ATTEMPTS} failed ({last_err})")
    return {"voice_path": None, "audio_generated": False, "error": last_err}
