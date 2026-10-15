# Arabic Reels Generator

Topic in → finished vertical Arabic reel out (1080x1920, ~45-55s, narrated,
captioned, real or drawn visuals). One command:

```bash
./make_reel.sh "الفائدة المركبة: كيف تتضاعف أموالك وأنت نائم" my_reel
./make_reel.sh "لماذا البنوك لا تنام" banks --addvid            # + stock video cuts (4-7s each)
./make_reel.sh "التضخم ببساطة" inflation --style draw --addvid  # illustrated/animated look
```

Output: `reels/<name>.mp4` + `reels/<name>.credits.json` (every asset's
source + license, for copyright audit).

## How it works

```
topic
  → scene_planner/write_short.py   one DeepSeek call: Arabic script (hook →
                                   segments → punchy ending) + per-segment
                                   English stock-search queries
  → render/build_video.py          per segment: Gemini narration (edge-tts
                                   fallback), Pexels/Pixabay/ComfyUI visuals,
                                   Ken Burns motion,
                                   crossfades, global color grade + grain +
                                   vignette, chunk-flash Arabic captions,
                                   optional music bed
  → reels/<name>.mp4
```

Each reel uses a DeepSeek call and may use Gemini narration. Service limits
and pricing depend on your API accounts; edge-tts and stock media are
available as free options.

## Setup from a fresh clone

Requires Python 3.10+ and FFmpeg with `ffmpeg`, `ffprobe`, and the `subtitles`
filter available on `PATH`. The renderer uses the bundled Arabic fonts.

```bash
python3 -m venv scene_planner/venv
scene_planner/venv/bin/python -m pip install -r scene_planner/requirements.txt
python3 -m venv render/venv
render/venv/bin/python -m pip install -r render/requirements.txt
cp scene_planner/.env.example scene_planner/.env
```

Edit `scene_planner/.env` with `DEEPSEEK_API_KEY` for script writing and at
least one stock media key: `PEXELS_API_KEY` for real footage, or
`PIXABAY_API_KEY` for real or drawn visuals. `GEMINI_API_KEY` enables the
default Gemini narration; without it, the renderer falls back to edge-tts.
The `.env` file stays local and is ignored by Git.

Music is optional: put tracks you have permission to use in
`render/assets/music/` (see its README). Use `--no-music` to skip the music bed.
For `--style gen`, run ComfyUI and set `COMFY_URL` or pass `--comfy-url`.

## Publish the source on GitHub

The Git ignore rules exclude API keys, generated media, caches, virtual
environments, and local music. Review what will be committed before pushing:

```bash
git init -b main
git add .
git status --short
git commit -m "Initial source release"
git remote add origin https://github.com/YOUR-USER/YOUR-REPO.git
git push -u origin main
```

Create the empty GitHub repository first, and replace the example remote URL
with yours. GitHub stores this project's source; generating reels still runs
locally with the API keys and FFmpeg configured above. If an `.env` file was
ever committed previously, ignoring it now does not remove it from history:
rotate those keys before publishing.

## Flags (pass after the name)

| Flag | Effect |
|------|--------|
| `--addvid` | mix in short topic-matched stock video cuts (4-7s) |
| `--style draw` | Pixabay illustrations/vectors/animations instead of real footage |
| `--style gen` | generate images with ComfyUI |
| `--edge` | use edge-tts narration |
| `--no-music` | skip the music bed |

## Notes

- Re-running the same name resumes (cached narration/media in `render/work_<name>/`).
- Pixabay API compliance: search responses cached 24h (`render/.api_cache/`),
  rate-limit headers honored, no mass downloading.
- Captions are chunk-flash (2-3 words, pop-in) because libass scrambles RTL
  word order with any mid-line tag — don't reintroduce karaoke tags.
- edge-tts uses Microsoft's endpoint unofficially; review its terms before
  relying on it for published work.
