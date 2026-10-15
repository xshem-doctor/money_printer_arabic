#!/usr/bin/env python3
"""Build one vertical reel (30-60s) from a script JSON (write_short.py or
scene_planner output).

Visual pipeline ("connected video", not a slideshow):
  - every junction between clips is a 0.25s crossfade (xfade), with each
    outgoing clip frozen-extended by the fade time so total length still
    matches the narration exactly
  - one global color grade + film grain + vignette applied to the whole
    timeline in the caption-burn pass, so mismatched stock reads as one
    production
  - optional continuous music bed from render/assets/music/, ducked under
    the narration
  - audio gets real silence gaps matching the per-segment padding, so
    captions/audio/video can never drift (they previously drifted ~0.35s
    per segment)

Style routing (--style): "real" = Pexels + Pixabay photos/videos;
"draw" = Pixabay illustrations/vectors. Every fetched asset is logged to
<output>.credits.json with its source and license.

Resumable: re-running skips any audio/media/clip file that already exists.
"""
import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import edge_tts
import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

import captions
import comfy_media
import gemini_tts
import stock_media

FPS = 30
WIDTH, HEIGHT = 1080, 1920
EDGE_VOICE = "ar-EG-ShakirNeural"  # the original free voice, used by --edge
# Default narration: Gemini Charon with this delivery direction.
DEFAULT_STYLE = "energetic punchy finance explainer tone"
SCENE_PADDING_SEC = 0.35
SECONDS_PER_IMAGE = 3.0
MAX_IMAGES_PER_SEGMENT = 4
ZOOM_RATE = 0.0014
XFADE_SEC = 0.25
MUSIC_VOLUME = 0.12
MAX_VIDEO_SEC = 7.0
MIN_VIDEO_SEC = 2.0
FONT_DIR = Path(__file__).parent / "assets" / "fonts"
FONT_BOLD = FONT_DIR / "NotoSansArabic-Bold.ttf"
FONT_REGULAR = FONT_DIR / "NotoSansArabic-Regular.ttf"
MUSIC_DIR = Path(__file__).parent / "assets" / "music"
RTL_KW = {"direction": "rtl", "language": "ar"}

# one uniform look for every clip: gentle contrast/saturation lift + warm
# highlights / cool shadows + grain + vignette (applied in the burn pass)
GRADE_VF = (
    "eq=contrast=1.05:saturation=1.12,"
    "colorbalance=rh=.04:bh=-.04:rs=.02:bs=-.02,"
    "vignette,"
    "noise=alls=5:allf=t"
)

PALETTE = [
    "#F4B942", "#3CB4AC", "#E85D4E", "#5A67D8", "#7C9A47",
    "#B15FA6", "#4C7EA8", "#D97A4D", "#6B9E78",
]

# ---------- logging ----------
# Every line is timestamped with elapsed seconds and mirrored to
# <work-dir>/build.log, so a silent hang is always distinguishable from work.

_START = time.time()
_LOG_FILE: Path | None = None


def log(msg: str):
    line = f"[{time.time() - _START:6.1f}s] {msg}"
    print(line, flush=True)
    if _LOG_FILE:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def _timed(label: str):
    """Context manager: logs '<label> ...' on entry and '<label> done (Xs)' on exit."""
    class _T:
        def __enter__(self):
            self.t0 = time.time()
            log(f"{label} ...")
            return self

        def __exit__(self, *exc):
            log(f"{label} done ({time.time() - self.t0:.1f}s)")
    return _T()


# ---------- chapters ----------

def get_chapters(segments: list[dict]) -> list[dict]:
    chapters, start, name = [], 0, "intro"
    for i, seg in enumerate(segments):
        if seg["scene"] == "title_card":
            if i > start:
                chapters.append({"name": name, "segments": segments[start:i]})
            start = i
            name = seg["text"]
    chapters.append({"name": name, "segments": segments[start:]})
    return chapters


# ---------- audio ----------

async def synth_audio(sem, seg, audio_dir: Path, tts: dict, retries: int = 4) -> bool:
    """Returns True if synthesized now, False if already cached."""
    out_path = audio_dir / f"{seg['id']:04d}.mp3"
    if out_path.exists():
        return False
    async with sem:
        if tts["engine"] == "gemini":
            # Blocking HTTP call — run it off the event loop.
            await asyncio.to_thread(
                gemini_tts.synthesize,
                seg["text"], out_path, tts["api_key"],
                tts["voice"], tts["model"], tts["style"], 5, log,
            )
            return True

        last_err = None
        for attempt in range(1, retries + 1):
            try:
                await edge_tts.Communicate(seg["text"], tts["voice"]).save(str(out_path))
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
                log(f"  ! TTS segment {seg['id']} attempt {attempt}/{retries} failed ({e}); retrying")
                await asyncio.sleep(1.5 * attempt)
        raise RuntimeError(f"segment {seg['id']} audio failed: {last_err}")


async def run_audio_phase(segments, audio_dir: Path, concurrency: int, tts: dict):
    audio_dir.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    tasks = [asyncio.ensure_future(synth_audio(sem, seg, audio_dir, tts)) for seg in segments]
    done = 0
    for fut in asyncio.as_completed(tasks):
        fresh = await fut
        done += 1
        log(f"  narration {done}/{len(tasks)}{'' if fresh else ' (cached)'}")


def ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def make_silence(duration: float, out_path: Path):
    """Silence matching edge-tts output (24kHz mono mp3) for inter-segment gaps."""
    if out_path.exists():
        return
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono",
         "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "48k", str(out_path)],
        check=True, capture_output=True,
    )


def trim_to_duration(segments, audio_dir: Path, target: float, tolerance: float):
    kept, total = [], 0.0
    for seg in segments:
        dur = ffprobe_duration(audio_dir / f"{seg['id']:04d}.mp3") + SCENE_PADDING_SEC
        if kept and total + dur > target + tolerance:
            break
        kept.append(seg)
        total += dur
        if total >= target:
            break
    return kept


# ---------- stills ----------

def render_title_image(text: str, color: str, out_path: Path):
    img = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(FONT_BOLD), 110)
    words, lines, cur = text.split(), [], []
    for w in words:
        cand = " ".join(cur + [w])
        if draw.textbbox((0, 0), cand, font=font, **RTL_KW)[2] <= WIDTH - 140 or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    line_h = 140
    y = HEIGHT / 2 - (line_h * len(lines)) / 2
    for line in lines:
        w = draw.textbbox((0, 0), line, font=font, **RTL_KW)[2]
        draw.text(((WIDTH - w) / 2, y), line, font=font, fill="#FFFFFF",
                   stroke_fill="#000000", stroke_width=5, **RTL_KW)
        y += line_h
    img.save(out_path)


def make_fallback_image(color: str, out_path: Path):
    Image.new("RGB", (WIDTH, HEIGHT), color).save(out_path)


def _wrap_rtl(draw, text, font, max_width):
    words, lines, cur = text.split(), [], []
    for w in words:
        cand = " ".join(cur + [w])
        if draw.textbbox((0, 0), cand, font=font, **RTL_KW)[2] <= max_width or not cur:
            cur.append(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
    if cur:
        lines.append(" ".join(cur))
    return lines


def render_card(text: str, subtitle: str, color: str, out_path: Path,
                accent: str = "#43D6FF"):
    """Branded intro/outro card: solid ground, a thin accent rule, big headline,
    optional smaller line beneath."""
    img = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(img)

    head_font = ImageFont.truetype(str(FONT_BOLD), 118)
    lines = _wrap_rtl(draw, text, head_font, WIDTH - 160)
    line_h = 150
    block_h = line_h * len(lines)
    y = HEIGHT / 2 - block_h / 2

    # accent rule above the headline
    rule_w = int(WIDTH * 0.18)
    draw.rectangle(
        [(WIDTH - rule_w) // 2, int(y - 70), (WIDTH + rule_w) // 2, int(y - 58)],
        fill=accent,
    )

    for line in lines:
        w = draw.textbbox((0, 0), line, font=head_font, **RTL_KW)[2]
        draw.text(((WIDTH - w) / 2, y), line, font=head_font, fill="#FFFFFF",
                  stroke_fill="#000000", stroke_width=6, **RTL_KW)
        y += line_h

    if subtitle:
        sub_font = ImageFont.truetype(str(FONT_REGULAR), 58)
        y += 96  # clear the headline's descenders (Arabic ع/ج dip well below baseline)
        for sline in _wrap_rtl(draw, subtitle, sub_font, WIDTH - 240):
            w = draw.textbbox((0, 0), sline, font=sub_font, **RTL_KW)[2]
            draw.text(((WIDTH - w) / 2, y), sline, font=sub_font, fill=accent,
                      stroke_fill="#000000", stroke_width=3, **RTL_KW)
            y += 82

    img.save(out_path)


# ---------- clips ----------

MOTIONS = ("zoom_in", "zoom_out", "pan_right", "pan_left")
_CENTER = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"


def _motion_expr(motion: str, total_frames: int) -> str:
    if motion == "zoom_in":
        return f"zoompan=z='min(zoom+{ZOOM_RATE},1.22)':{_CENTER}:d={total_frames}"
    if motion == "zoom_out":
        return f"zoompan=z='if(lte(zoom,1.0),1.22,max(zoom-{ZOOM_RATE},1.0))':{_CENTER}:d={total_frames}"
    if motion == "pan_right":
        return f"zoompan=z='1.18':x='(iw-iw/zoom)*(on/{total_frames})':y='ih/2-(ih/zoom/2)':d={total_frames}"
    return f"zoompan=z='1.18':x='(iw-iw/zoom)*(1-on/{total_frames})':y='ih/2-(ih/zoom/2)':d={total_frames}"


def make_image_clip(image_path: Path, duration: float, out_path: Path, motion: str = "zoom_in"):
    if out_path.exists():
        return
    total_frames = max(1, round(duration * FPS))
    precrop = f"crop=w='min(iw,ih*{WIDTH}/{HEIGHT})':h='min(ih,iw*{HEIGHT}/{WIDTH})'"
    vf = (
        f"scale={WIDTH*6}:-2,{precrop},{_motion_expr(motion, total_frames)}"
        f":s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(image_path), "-vf", vf,
         "-t", str(duration), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out_path)],
        check=True, capture_output=True,
    )


def make_video_clip(src_path: Path, duration: float, out_path: Path):
    if out_path.exists():
        return
    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},setsar=1,fps={FPS}"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src_path), "-vf", vf, "-t", str(duration),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(out_path)],
        check=True, capture_output=True,
    )


# ---------- assembly ----------

def xfade_assemble(clips: list[tuple[Path, float]], out_path: Path, fade: float = XFADE_SEC):
    """Crossfade-join clips. Each outgoing clip is frozen-extended (tpad) by
    the fade time, so the assembled length equals the sum of planned clip
    durations exactly — narration and captions stay in sync."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", str(clips[0][0]), "-c", "copy", str(out_path)],
                       check=True, capture_output=True)
        return

    cmd = ["ffmpeg", "-y"]
    for path, _ in clips:
        cmd += ["-i", str(path)]

    parts, offsets = [], []
    acc = 0.0
    for i, (_, dur) in enumerate(clips):
        acc += dur
        offsets.append(acc)
    for i in range(len(clips) - 1):
        parts.append(f"[{i}:v]tpad=stop_mode=clone:stop_duration={fade}[p{i}]")
    parts.append(f"[{len(clips)-1}:v]null[p{len(clips)-1}]")

    prev = "p0"
    for i in range(1, len(clips)):
        out_label = f"x{i}" if i < len(clips) - 1 else "vout"
        parts.append(
            f"[{prev}][p{i}]xfade=transition=fade:duration={fade}:offset={offsets[i-1]:.3f}[{out_label}]"
        )
        prev = out_label

    cmd += ["-filter_complex", ";".join(parts), "-map", "[vout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out_path)]
    subprocess.run(cmd, check=True, capture_output=True)


def concat_audio(paths: list[Path], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.parent / f"{out_path.stem}_concat.txt"
    list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in paths), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c:a", "aac", str(out_path)],
        check=True, capture_output=True,
    )
    list_file.unlink()


def pick_music() -> Path | None:
    if not MUSIC_DIR.is_dir():
        return None
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")]
    return random.choice(tracks) if tracks else None


def mux(video_path: Path, audio_path: Path, out_path: Path, music: Path | None):
    if music:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
             "-stream_loop", "-1", "-i", str(music),
             "-filter_complex",
             f"[2:a]volume={MUSIC_VOLUME}[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)],
            check=True, capture_output=True,
        )
    else:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-i", str(audio_path),
             "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-shortest", str(out_path)],
            check=True, capture_output=True,
        )


def burn_captions_and_grade(video_path: Path, ass_path: Path, out_path: Path):
    """One re-encode pass: grade + grain + vignette, then captions on top (ungraded)."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(video_path),
         "-vf", f"{GRADE_VF},subtitles={ass_path}:fontsdir={FONT_DIR}",
         "-c:a", "copy", str(out_path)],
        check=True, capture_output=True,
    )


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--chapter-index", type=int, default=0)
    ap.add_argument("--target-duration", type=float, default=45.0)
    ap.add_argument("--tolerance", type=float, default=15.0)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--work-dir", default="work")
    ap.add_argument("--style", choices=("real", "draw", "gen"), default="real",
                    help="real = stock photos/footage; draw = illustrations/vectors (needs PIXABAY_API_KEY); "
                         "gen = AI-generated images via ComfyUI (set COMFY_URL if not local)")
    ap.add_argument("--comfy-url", default=None,
                    help="ComfyUI base URL for --style gen (default $COMFY_URL or http://127.0.0.1:8188)")
    ap.add_argument("--seed", type=int, default=None,
                    help="base seed for --style gen; same seed + same script = same images")
    ap.add_argument("--addvid", action="store_true",
                    help="mix in short stock video cuts (4-7s, topic-matched) where available")
    ap.add_argument("--no-music", action="store_true", help="skip the background music bed")
    voice_group = ap.add_mutually_exclusive_group()
    voice_group.add_argument("--girl", action="store_true",
                             help="Gemini female voice (Kore)")
    voice_group.add_argument("--male", action="store_true",
                             help="Gemini male voice (Charon)")
    voice_group.add_argument("--edge", action="store_true",
                             help="use the original free edge-tts voice (Shakir)")
    voice_group.add_argument("--voice", default=None,
                             help="explicit voice name; pair with --voice-engine to pick the backend")
    ap.add_argument("--voice-engine", choices=("edge", "gemini"), default=None,
                    help="default: gemini (Charon)")
    ap.add_argument("--tts-model", default=gemini_tts.DEFAULT_MODEL,
                    help="Gemini TTS model")
    ap.add_argument("--tts-style", default="",
                    help="delivery direction for Gemini, e.g. 'energetic finance explainer tone'")
    ap.add_argument("--outro", default="تابع للمزيد",
                    help="end-card headline (empty string disables the outro)")
    ap.add_argument("--outro-sub", default="", help="smaller line under the end card headline")
    ap.add_argument("--outro-seconds", type=float, default=2.2)
    ap.add_argument("--intro", default="",
                    help="optional opening card headline; off by default — it costs retention")
    ap.add_argument("--intro-seconds", type=float, default=1.2)
    args = ap.parse_args()

    load_dotenv(Path(__file__).parent.parent / "scene_planner" / ".env")
    keys = {
        "pexels": os.environ.get("PEXELS_API_KEY"),
        "pixabay": os.environ.get("PIXABAY_API_KEY"),
    }
    if args.style == "draw" and not keys["pixabay"]:
        print("--style draw needs PIXABAY_API_KEY in scene_planner/.env\n"
              "(free key: https://pixabay.com/api/docs/)", file=sys.stderr)
        sys.exit(1)
    comfy_url = args.comfy_url or comfy_media.DEFAULT_URL
    if args.style == "gen":
        if not comfy_media.is_available(comfy_url):
            print(f"--style gen needs a reachable ComfyUI at {comfy_url}\n"
                  "  - start it with: ~/ai-images/run.sh (add --listen 0.0.0.0 for remote access)\n"
                  "  - or point elsewhere: --comfy-url http://HOST:8188", file=sys.stderr)
            sys.exit(1)
        log(f"ComfyUI reachable at {comfy_url}")
    elif not keys["pexels"] and not keys["pixabay"]:
        print("no media API keys set (PEXELS_API_KEY / PIXABAY_API_KEY in scene_planner/.env)", file=sys.stderr)
        sys.exit(1)
    base_seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)

    all_segments = json.loads(Path(args.input).read_text(encoding="utf-8"))
    chapters = get_chapters(all_segments)
    if args.chapter_index >= len(chapters):
        print(f"only {len(chapters)} chapters (0-{len(chapters)-1})", file=sys.stderr)
        sys.exit(1)
    chapter = chapters[args.chapter_index]
    work = Path(args.work_dir)
    audio_dir, media_dir, clip_dir = (work / d for d in ("audio", "media", "clips"))
    for d in (audio_dir, media_dir, clip_dir):
        d.mkdir(parents=True, exist_ok=True)

    global _LOG_FILE
    _LOG_FILE = work / "build.log"
    log(f"chapter[{args.chapter_index}] = \"{chapter['name']}\" "
        f"({len(chapter['segments'])} segments, style={args.style})")
    log(f"log file: {_LOG_FILE}")

    # ---- pick the voice engine ----
    # Default is Gemini Charon with the energetic delivery; --edge restores the
    # original edge-tts Shakir voice.
    if args.girl:
        engine, voice = "gemini", gemini_tts.VOICES["girl"]
    elif args.male:
        engine, voice = "gemini", gemini_tts.VOICES["male"]
    elif args.edge or args.voice_engine == "edge":
        engine, voice = "edge", (args.voice or EDGE_VOICE)
    else:
        engine, voice = "gemini", (args.voice or gemini_tts.VOICES["male"])

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if engine == "gemini" and not api_key:
        # Don't hard-fail: fall back so a missing key degrades rather than blocks.
        log("  ! GEMINI_API_KEY not set — falling back to the edge voice")
        engine, voice = "edge", EDGE_VOICE

    style = args.tts_style if args.tts_style else (DEFAULT_STYLE if engine == "gemini" else "")
    tts = {
        "engine": engine,
        "voice": voice,
        "model": args.tts_model,
        "style": style,
        "api_key": api_key,
    }
    # Free-tier Gemini is rate-limited per minute; hammering it just burns retries.
    audio_concurrency = 2 if engine == "gemini" else args.concurrency

    log(f"[1/6] narrating chapter ({len(chapter['segments'])} segments) "
        f"— {engine}:{voice}" + (f" · style=\"{style}\"" if style else ""))
    asyncio.run(run_audio_phase(chapter["segments"], audio_dir, audio_concurrency, tts))

    log("[2/6] trimming to target duration")
    segments = trim_to_duration(chapter["segments"], audio_dir, args.target_duration, args.tolerance)
    total = sum(ffprobe_duration(audio_dir / f"{s['id']:04d}.mp3") + SCENE_PADDING_SEC for s in segments)
    log(f"  kept {len(segments)}/{len(chapter['segments'])} segments, ~{total:.1f}s")

    log("[3/6] fetching media + building clips")
    session = requests.Session()
    seg_durations: dict[int, float] = {}
    timeline_clips: list[tuple[Path, float]] = []
    audio_parts: list[Path] = []
    credits: list[dict] = []
    color = PALETTE[args.chapter_index % len(PALETTE)]

    silence_path = audio_dir / "_gap.mp3"
    make_silence(SCENE_PADDING_SEC, silence_path)

    def add_card(kind: str, headline: str, subtitle: str, seconds: float):
        """Append an intro/outro card to the timeline, with matching silence so
        audio and video stay the same length."""
        img = media_dir / f"_{kind}.jpg"
        if not img.exists():
            render_card(headline, subtitle, "#12161A", img)
        clip = clip_dir / f"_{kind}.mp4"
        if clip.exists():
            clip.unlink()  # cheap to redo, and text may have changed
        make_image_clip(img, seconds, clip, "zoom_in")
        sil = audio_dir / f"_{kind}_sil.mp3"
        make_silence(seconds, sil)
        return clip, sil

    if args.intro.strip():
        clip, sil = add_card("intro", args.intro.strip(), "", args.intro_seconds)
        timeline_clips.append((clip, args.intro_seconds))
        audio_parts.append(sil)
        log(f"  intro card: \"{args.intro.strip()}\" ({args.intro_seconds}s)")

    credits_store = work / "credits.json"
    if credits_store.exists():  # persists across resumed runs (cached media logs nothing new)
        credits.extend(json.loads(credits_store.read_text(encoding="utf-8")))

    def log_credit(seg_id, kind, item):
        credits.append({
            "segment": seg_id, "kind": kind, "source": item["source"],
            "page": item.get("page", ""), "url": item["url"],
            "license": stock_media.LICENSES[item["source"]],
        })

    for seg in segments:
        audio_path = audio_dir / f"{seg['id']:04d}.mp3"
        duration = ffprobe_duration(audio_path) + SCENE_PADDING_SEC
        seg_durations[seg["id"]] = duration
        audio_parts += [audio_path, silence_path]  # real gap keeps captions/audio in sync

        if seg["scene"] == "title_card":
            img_path = media_dir / f"{seg['id']:04d}_title.jpg"
            if not img_path.exists():
                render_title_image(seg["text"], color, img_path)
            clip_path = clip_dir / f"{seg['id']:04d}_0.mp4"
            make_image_clip(img_path, duration, clip_path)
            timeline_clips.append((clip_path, duration))
            continue

        remaining = duration
        vid_note = ""

        if args.addvid:
            vid_src = media_dir / f"{seg['id']:04d}_vid_src.mp4"
            vid_dur = 0.0
            if vid_src.exists():
                vid_dur = ffprobe_duration(vid_src)
                log(f"  seg {seg['id']}: stock video cached")
            else:
                log(f"  seg {seg['id']}: searching stock video for \"{seg['search_query']}\"")
                found = stock_media.find_video(session, keys, seg["search_query"], args.style)
                if found:
                    log(f"  seg {seg['id']}: downloading video from {found['source']} (can take 10-60s on slow network)")
                    if stock_media.download(session, found["url"], vid_src):
                        vid_dur = ffprobe_duration(vid_src)
                        log(f"  seg {seg['id']}: video downloaded ({vid_src.stat().st_size // 1024}KB, {vid_dur:.1f}s)")
                        log_credit(seg["id"], "video", found)
                    else:
                        log(f"  seg {seg['id']}: ! video download failed, falling back to images")
                else:
                    log(f"  seg {seg['id']}: no stock video found, using images")
            if vid_dur >= MIN_VIDEO_SEC:
                if vid_dur >= duration and duration <= MAX_VIDEO_SEC:
                    cut = duration
                else:
                    cut = min(vid_dur, MAX_VIDEO_SEC)
                    if 0 < duration - cut < 1.0:
                        cut = duration - 1.0
                if cut >= MIN_VIDEO_SEC:
                    clip_path = clip_dir / f"{seg['id']:04d}_vid.mp4"
                    make_video_clip(vid_src, cut, clip_path)
                    timeline_clips.append((clip_path, cut))
                    remaining = duration - cut
                    vid_note = f"video {cut:.1f}s + "

        n_images = 0
        if remaining > 0.05:
            n_images = max(1, min(MAX_IMAGES_PER_SEGMENT, round(remaining / SECONDS_PER_IMAGE)))
            per_image_dur = remaining / n_images

            generated: list[bytes] = []
            if args.style == "gen":
                missing = [k for k in range(n_images)
                           if not (media_dir / f"{seg['id']:04d}_{k}.jpg").exists()]
                if missing:
                    seg_seed = base_seed + seg["id"] * 100
                    prompt = seg.get("image_prompt") or seg["search_query"]
                    log(f"  seg {seg['id']}: generating {len(missing)} image(s) — \"{prompt[:60]}\"")
                    try:
                        generated = comfy_media.generate(
                            prompt, len(missing), seg_seed, comfy_url,
                            theme=seg.get("visual_theme", ""), log=log)
                        log(f"  seg {seg['id']}: got {len(generated)} image(s)")
                    except Exception as e:  # noqa: BLE001
                        log(f"  seg {seg['id']}: ! generation failed ({e}); falling back to stock")

            photos = []
            if args.style != "gen" or (not generated and n_images):
                stock_style = "real" if args.style == "gen" else args.style
                photos = stock_media.find_photos(session, keys, seg["search_query"],
                                                 n_images, stock_style)

            gen_queue = list(generated)
            for k in range(n_images):
                img_path = media_dir / f"{seg['id']:04d}_{k}.jpg"
                if not img_path.exists():
                    if gen_queue:
                        img_path.write_bytes(gen_queue.pop(0))
                        credits.append({"segment": seg["id"], "kind": "image",
                                        "source": "generated", "page": "", "url": "",
                                        "license": comfy_media.LICENSE_NOTE})
                    else:
                        item = photos[k] if k < len(photos) else None
                        if item and stock_media.download(session, item["url"], img_path):
                            log_credit(seg["id"], "image", item)
                        else:
                            log(f"  seg {seg['id']}: ! no photo for slot {k}, using solid color")
                            make_fallback_image(color, img_path)
                clip_path = clip_dir / f"{seg['id']:04d}_{k}.mp4"
                motion = MOTIONS[len(timeline_clips) % len(MOTIONS)]
                make_image_clip(img_path, per_image_dur, clip_path, motion)
                timeline_clips.append((clip_path, per_image_dur))

        log(f"  segment {seg['id']} ready: {vid_note}{n_images} image(s)")

    if args.outro.strip():
        clip, sil = add_card("outro", args.outro.strip(), args.outro_sub.strip(),
                             args.outro_seconds)
        timeline_clips.append((clip, args.outro_seconds))
        audio_parts.append(sil)
        log(f"  outro card: \"{args.outro.strip()}\" ({args.outro_seconds}s)")

    silent_video = work / "silent_video.mp4"
    if silent_video.exists():
        silent_video.unlink()
    with _timed(f"[4/6] assembling {len(timeline_clips)} clips with crossfades (CPU-heavy, ~10-60s)"):
        xfade_assemble(timeline_clips, silent_video)
    full_audio = work / "full_audio.m4a"
    concat_audio(audio_parts, full_audio)

    music = None if args.no_music else pick_music()
    muxed = work / "muxed.mp4"
    with _timed(f"[5/6] muxing (music: {music.name if music else 'none — drop tracks in render/assets/music/'})"):
        mux(silent_video, full_audio, muxed, music)

    offset = 0.0
    timeline = []
    for seg in segments:
        d = seg_durations[seg["id"]]
        timeline.append((seg, offset, d))
        offset += d
    ass_path = work / "captions.ass"
    captions.build_ass(timeline, ass_path, WIDTH, HEIGHT)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with _timed("[6/6] grading + burning captions (CPU-heavy, ~20-90s)"):
        burn_captions_and_grade(muxed, ass_path, out)

    seen, deduped = set(), []
    for c in credits:
        if c["url"] not in seen:
            seen.add(c["url"])
            deduped.append(c)
    credits_store.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    credits_path = out.with_suffix(".credits.json")
    credits_path.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"DONE: {out} (~{offset:.1f}s) | credits: {credits_path.name}")


if __name__ == "__main__":
    main()
