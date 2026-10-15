#!/usr/bin/env python3
"""Generate a complete short/reel script from just a topic — ONE DeepSeek
call per short (script + scene types + image search queries all in the same
response), so the LLM cost per video is a single small request.

Output is the same JSON format render/build_video.py already consumes.

Usage:
    venv/bin/python write_short.py "الفائدة المركبة" script.json
    venv/bin/python write_short.py "why banks never sleep" script.json --language ar
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = """You write scripts for short vertical videos (reels, 30-60 seconds) in ARABIC \
(Modern Standard Arabic, conversational tone — like the narration of a popular explainer channel: \
vivid, a little funny, concrete examples with numbers).

Structure the script as 6-10 SHORT segments. Rules:
- Segment 1 is the HOOK: a surprising fact, question, or bold claim that stops the scroll.
- Each segment is 1-2 short sentences (spoken length 4-8 seconds).
- The last segment is a punchy takeaway or twist — NOT a generic "follow for more".
- Total spoken length must fit 40-55 seconds.

For each segment also provide:
- "scene": one of "text_card" (default), "counter_scene" (the narration centers on one big number; \
add slots {"number": <number>, "unit": "<$ or % or empty>"}), or "list_scene" (enumerates items; \
add slots {"items": ["...", "..."]} with 2-4 SHORT Arabic items). Use counter/list only when truly natural.
- "search_query": an ENGLISH stock-photo search phrase, 2-5 words, CONCRETE and VISUAL — something \
a photographer could actually shoot (e.g. "hand stacking coins", "crowded supermarket aisle", \
"man staring at laptop stressed"). Never abstract concepts. Vary the queries so consecutive \
segments get visually different images, BUT keep one visual thread through the whole reel: \
pick a protagonist type and a setting family in the first segment (e.g. "young man, office/city \
world") and reuse them in most queries, so the reel feels like one continuous story rather than \
random stock. NEVER include brand names, company names, celebrities, or fictional characters \
in search queries.

- "image_prompt": an ENGLISH prompt for an AI image generator describing THIS segment's visual. \
One clear subject doing one clear action, plus where it happens. 8-20 words. Describe only the \
scene content — no style words (style is added separately). Show the idea through objects and \
body language, never through written words in the image. Example: "a young man sitting on his bed \
at night looking at a glowing phone screen".

Also provide ONE global "visual_theme" for the whole reel: a short English description of the \
recurring protagonist and palette that every image should share, e.g. "same young man with short \
dark hair wearing a simple teal shirt, warm orange and teal color palette". Keep it under 25 words. \
This is what makes all the images look like one continuous story instead of unrelated pictures.

Consecutive segments must differ in framing (wide shot, close-up on hands, over-the-shoulder, \
object-only) so the video does not feel static.

NEVER include brand names, company names, celebrities, or fictional characters in search_query \
or image_prompt.

Reply with ONLY a JSON object:
{"title": "<short arabic title>", "visual_theme": "<english>", "segments": [{"text": "...", \
"scene": "...", "slots": {...}, "search_query": "...", "image_prompt": "..."}, ...]}"""


def write_script(api_key: str, topic: str, retries: int = 3) -> dict:
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Topic: {topic}"},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.8,  # creative writing — higher than classification
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            t0 = time.time()
            print(f"calling DeepSeek (attempt {attempt}, usually 15-60s) ...", flush=True)
            resp = requests.post(DEEPSEEK_URL, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            print(f"DeepSeek responded in {time.time() - t0:.1f}s", flush=True)
            return json.loads(resp.json()["choices"][0]["message"]["content"])
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"! attempt {attempt}/{retries} failed ({type(e).__name__}); retrying", flush=True)
            time.sleep(2 * attempt)
    raise RuntimeError(f"script generation failed after {retries} attempts: {last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic", help="what the reel should be about (Arabic or English)")
    ap.add_argument("output", help="output JSON path (build_video.py format)")
    args = ap.parse_args()

    load_dotenv(Path(__file__).parent / ".env")
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not set (scene_planner/.env)", file=sys.stderr)
        sys.exit(1)

    print(f"writing short script for: {args.topic}")
    result = write_script(api_key, args.topic)

    visual_theme = result.get("visual_theme", "")
    segments = []
    for i, seg in enumerate(result.get("segments", [])):
        scene = seg.get("scene", "text_card")
        if scene not in ("text_card", "counter_scene", "list_scene"):
            scene = "text_card"
        segments.append({
            "id": i,
            "kind": "body",
            "text": seg["text"],
            "scene": scene,
            "slots": seg.get("slots") or {},
            "search_query": seg.get("search_query") or "abstract background",
            # used by --style gen; falls back to the stock query if absent
            "image_prompt": seg.get("image_prompt") or seg.get("search_query") or "",
            "visual_theme": visual_theme,
        })

    if not segments:
        print("model returned no segments", file=sys.stderr)
        sys.exit(1)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"title: {result.get('title', '(none)')}")
    if visual_theme:
        print(f"theme: {visual_theme}")
    for seg in segments:
        print(f"  [{seg['id']}] {seg['scene']:14s} | {seg['image_prompt'][:60]}")
    print(f"\nwrote {out} ({len(segments)} segments)")


if __name__ == "__main__":
    main()
