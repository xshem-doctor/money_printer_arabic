"""Gemini TTS backend.

Returns raw PCM (audio/L16, 24 kHz mono), which is converted to mp3 so the
rest of the pipeline — which measures durations with ffprobe and concatenates
mp3s — needs no changes.

Free-tier Gemini is rate-limited per minute rather than per character, so
429s are expected under concurrency; they're retried with backoff instead of
being treated as failures.
"""
import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Friendly aliases for the two voices wired to --girl / --male.
VOICES = {
    "girl": "Kore",
    "male": "Charon",
}


def _request(text: str, voice: str, model: str, api_key: str, timeout: int = 180) -> bytes:
    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}
            },
        },
    }
    req = urllib.request.Request(
        ENDPOINT.format(model=model, key=api_key),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())

    try:
        inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"unexpected Gemini response: {json.dumps(data)[:300]}") from e
    return base64.b64decode(inline["data"])


def synthesize(
    text: str,
    out_path: Path,
    api_key: str,
    voice: str = "Charon",
    model: str = DEFAULT_MODEL,
    style: str = "",
    retries: int = 5,
    log=print,
) -> Path:
    """Synthesize `text` to mp3 at `out_path`. Raises on unrecoverable failure."""
    prompt = f"{style.strip()}: {text}" if style.strip() else text

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            pcm = _request(prompt, voice, model, api_key)
            break
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:200]
            except Exception:
                pass
            last_err = f"HTTP {e.code}: {detail}"
            # 429 = free-tier rate limit; 5xx = transient. Both worth waiting out.
            wait = min(60, 5 * attempt) if e.code in (429, 500, 503) else 2 * attempt
            log(f"    ! gemini tts attempt {attempt}/{retries} — {last_err[:90]}; waiting {wait}s")
            time.sleep(wait)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            log(f"    ! gemini tts attempt {attempt}/{retries} failed ({e}); retrying")
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"gemini tts failed after {retries} attempts: {last_err}")

    raw = out_path.with_suffix(".pcm")
    raw.write_bytes(pcm)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "s16le", "-ar", "24000", "-ac", "1",
         "-i", str(raw), "-b:a", "96k", str(out_path)],
        check=True, capture_output=True,
    )
    raw.unlink(missing_ok=True)
    return out_path
