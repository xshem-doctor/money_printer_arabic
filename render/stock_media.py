"""Style-aware stock media fetching from whitelisted free-license sources.

Sources (both allow commercial use, no attribution required):
  - Pexels  (photos + videos)          — style "real"
  - Pixabay (photos, illustrations,
             vectors + videos)         — style "real" fallback, primary for "draw"

Style routing:
  real: Pexels first, Pixabay photos as fallback.
  draw: Pixabay illustrations/vectors only (Pexels has no drawn content).

Every successful fetch returns the source name so the caller can log a
credits manifest. Nothing here ever raises on a bad/missing result — callers
fall back to solid-color stills.
"""
import hashlib
import json
import time
from pathlib import Path

import requests

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"
PEXELS_PHOTO_URL = "https://api.pexels.com/v1/search"
PIXABAY_IMAGE_URL = "https://pixabay.com/api/"
PIXABAY_VIDEO_URL = "https://pixabay.com/api/videos/"

LICENSES = {
    "pexels": "Pexels License (free commercial use, no attribution required)",
    "pixabay": "Pixabay Content License (free commercial use, no attribution required)",
}

# Pixabay API terms REQUIRE search responses to be cached for 24 hours (and
# their returned media URLs are valid for exactly that long). Applied to both
# sources — it also spares Pexels quota and makes resumed runs API-silent.
CACHE_DIR = Path(__file__).parent / ".api_cache"
CACHE_TTL_SEC = 24 * 3600


def _cache_key(url: str, params: dict) -> Path:
    # exclude the api key from the cache identity
    ident = url + json.dumps({k: v for k, v in sorted(params.items()) if k != "key"})
    return CACHE_DIR / (hashlib.sha1(ident.encode()).hexdigest() + ".json")


def _get_json(session: requests.Session, url: str, params: dict, headers: dict | None = None, retries: int = 3):
    cache_path = _cache_key(url, params)
    if cache_path.exists() and time.time() - cache_path.stat().st_mtime < CACHE_TTL_SEC:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass  # corrupt cache entry — fall through to a live request

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, params=params, headers=headers or {}, timeout=20)
            if resp.status_code == 429:
                # honor the provider's own reset clock when it sends one
                reset = resp.headers.get("X-RateLimit-Reset")
                wait = min(float(reset), 60.0) if reset else 2.0 * attempt
                print(f"    ! rate-limited, waiting {wait:.0f}s", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            CACHE_DIR.mkdir(exist_ok=True)
            cache_path.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as e:
            print(f"    ! search attempt {attempt}/{retries} failed ({type(e).__name__}); retrying", flush=True)
            time.sleep(1.5 * attempt)
    return None


# ---------- pexels ----------

def _pexels_photos(session, key, query, count) -> list[dict]:
    data = _get_json(session, PEXELS_PHOTO_URL, {
        "query": query, "per_page": max(count, 5), "orientation": "portrait",
    }, headers={"Authorization": key})
    if not data or not data.get("photos"):
        return []
    return [{"url": p["src"]["large2x"], "source": "pexels", "page": p.get("url", "")}
            for p in data["photos"][:count]]


def _pexels_video(session, key, query, min_duration, target_height) -> dict | None:
    data = _get_json(session, PEXELS_VIDEO_URL, {
        "query": query, "per_page": 5, "orientation": "portrait",
    }, headers={"Authorization": key})
    if not data or not data.get("videos"):
        return None
    videos = data["videos"]
    video = next((v for v in videos if v.get("duration", 0) >= min_duration), videos[0])
    files = sorted(
        (f for f in video["video_files"] if f.get("height")),
        key=lambda f: abs(f["height"] - target_height),
    )
    if not files:
        return None
    return {"url": files[0]["link"], "duration": float(video.get("duration", 0)),
            "source": "pexels", "page": video.get("url", "")}


# ---------- pixabay ----------

def _pixabay_photos(session, key, query, count, image_type) -> list[dict]:
    data = _get_json(session, PIXABAY_IMAGE_URL, {
        "key": key, "q": query[:100], "image_type": image_type,
        "orientation": "vertical", "per_page": max(count, 5), "safesearch": "true",
    })
    if not data or not data.get("hits"):
        return []
    return [{"url": h.get("largeImageURL") or h.get("webformatURL"), "source": "pixabay",
             "page": h.get("pageURL", "")}
            for h in data["hits"][:count]]


def _pixabay_video(session, key, query, min_duration, video_type: str = "all") -> dict | None:
    data = _get_json(session, PIXABAY_VIDEO_URL, {
        "key": key, "q": query[:100], "video_type": video_type,
        "per_page": 5, "safesearch": "true",
    })
    if not data or not data.get("hits"):
        return None
    hits = data["hits"]
    hit = next((h for h in hits if h.get("duration", 0) >= min_duration), hits[0])
    # per docs, "large" can be present with an EMPTY url (size 0) — walk down
    # the renditions until one actually has a link
    rendition = None
    for size in ("large", "medium", "small", "tiny"):
        cand = hit.get("videos", {}).get(size)
        if cand and cand.get("url"):
            rendition = cand
            break
    if not rendition:
        return None
    return {"url": rendition["url"], "duration": float(hit.get("duration", 0)),
            "source": "pixabay", "page": hit.get("pageURL", "")}


# ---------- style-aware API ----------

def find_photos(session, keys: dict, query: str, count: int, style: str = "real") -> list[dict]:
    """Returns up to `count` dicts of {url, source, page}."""
    if style == "draw":
        if not keys.get("pixabay"):
            return []
        results = _pixabay_photos(session, keys["pixabay"], query, count, "illustration")
        if not results:
            results = _pixabay_photos(session, keys["pixabay"], query, count, "vector")
        return results

    results = _pexels_photos(session, keys["pexels"], query, count) if keys.get("pexels") else []
    if not results and keys.get("pixabay"):
        results = _pixabay_photos(session, keys["pixabay"], query, count, "photo")
    return results


def find_video(session, keys: dict, query: str, style: str = "real",
               min_duration: float = 3.0, target_height: int = 1920) -> dict | None:
    """Returns {url, duration, source, page} or None."""
    if style == "draw":
        if not keys.get("pixabay"):
            return None
        # proper API filter for animated content (docs: video_type=animation)
        return _pixabay_video(session, keys["pixabay"], query, min_duration, video_type="animation")

    found = _pexels_video(session, keys["pexels"], query, min_duration, target_height) if keys.get("pexels") else None
    if not found and keys.get("pixabay"):
        found = _pixabay_video(session, keys["pixabay"], query, min_duration, video_type="film")
    return found


def download(session: requests.Session, url: str, dest: Path, retries: int = 3) -> bool:
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=60)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return True
        except Exception as e:
            print(f"    ! download attempt {attempt}/{retries} failed ({type(e).__name__}); retrying", flush=True)
            time.sleep(1.5 * attempt)
    return False
