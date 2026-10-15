# scene_planner

`write_short.py` — generates a complete reel script from a topic in ONE
DeepSeek call: Arabic narration segments (hook first, 1-2 short sentences
each, punchy ending) plus a concrete English stock-media search query per
segment. Output feeds `render/build_video.py` directly.

```bash
venv/bin/python write_short.py "الفائدة المركبة" script.json
```

Normally invoked via `../make_reel.sh`, not directly.

Copy `.env.example` to `.env` and fill in the API keys you use. The local
`.env` file is ignored by Git. See the root README for fresh-clone setup.
