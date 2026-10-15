# Architecture

## The flow

```
topic string
     │
     ▼
scene_planner/write_short.py ─── ONE DeepSeek call ───┐
     │                                                 │
     │  returns per reel:                              │
     │    title                                        │
     │    visual_theme   (protagonist + palette,       │
     │                    shared by every image)       │
     │  returns per segment:                           │
     │    text          (Arabic narration)             │
     │    scene         (text_card|counter_scene|      │
     │                   list_scene)                   │
     │    slots         (numbers / list items)         │
     │    search_query  (English, for stock)           │
     │    image_prompt  (English, for generation)      │
     ▼                                                 │
work/<name>/script.json ◄────────────────────────────┘
     │
     ▼
render/build_video.py
     │
     ├─ [1] narrate      edge-tts (ar-EG-ShakirNeural), one mp3 per segment
     ├─ [2] trim         keep segments until target duration, using REAL
     │                   measured audio length
     ├─ [3] visuals      per segment, depending on --style:
     │                     real → Pexels photos/video, Pixabay fallback
     │                     draw → Pixabay illustrations/vectors/animation
     │                     gen  → ComfyUI (Stable Diffusion) via HTTP
     │                   each image becomes a clip with one of four Ken Burns
     │                   moves (zoom in/out, pan left/right), cycled so no two
     │                   neighbours match
     ├─ [4] assemble     xfade crossfades between every clip; each outgoing
     │                   clip is frozen-extended by the fade time so total
     │                   length still equals the narration exactly
     ├─ [5] mux          narration + optional music bed (ducked to 0.12)
     └─ [6] finish       color grade + grain + vignette, then burn captions
     │
     ▼
reels/<name>.mp4  +  reels/<name>.credits.json
```

## Modules

### `scene_planner/write_short.py`
One DeepSeek call writes the whole reel. Prompt enforces:
- segment 1 is a scroll-stopping hook
- 1-2 short sentences per segment (4-8s spoken)
- last segment is a payoff, not "follow for more"
- 40-55s total
- one `visual_theme` reused across all image prompts (this is what makes the
  reel feel like one story instead of random stock)
- consecutive segments must differ in framing (wide / close-up / over-shoulder)
- no brands, celebrities, or fictional characters

### `render/build_video.py`
Orchestrator. Everything is resumable — re-running skips any audio/media/clip
file that already exists, so a network drop costs only the in-flight item.
Timestamped progress goes to stdout and `work/<name>/build.log`.

Key constants: `FPS=30`, `1080x1920`, `SCENE_PADDING_SEC=0.35`,
`SECONDS_PER_IMAGE=3.0`, `MAX_IMAGES_PER_SEGMENT=4`, `XFADE_SEC=0.25`,
`ZOOM_RATE=0.0014`, `MUSIC_VOLUME=0.12`, video cuts clamped to 2-7s.

### `render/stock_media.py`
Pexels + Pixabay behind one style-aware interface. Caches every API response
for 24h in `render/.api_cache/` (Pixabay's terms require this), honours
`X-RateLimit-Reset` on 429, and walks video renditions large→medium→small→tiny
because Pixabay can return a `large` entry with an empty URL.

### `render/comfy_media.py`
Talks to ComfyUI's HTTP API: queues a workflow, polls `/history`, downloads the
PNGs from `/view`. Because images come back over HTTP, the renderer and the GPU
can live on different machines (`COMFY_URL`). Consistency comes from
`visual_theme` + a fixed style suffix + `base_seed + segment_id*100`.

### `render/captions.py`
Chunk-flash captions: 2-3 words at a time, centered, quick pop-in, timed by
splitting each segment's real audio duration proportionally to word length.
Deliberately *not* karaoke — see gotchas.

## Design decisions worth remembering

- **Rebuild, not re-edit.** The original goal was translating an existing
  video; extracting 22k frames proved useless. The script is the asset.
- **Stock → generated.** Stock never matched the narration well. ComfyUI
  generation solves matching *and* style consistency at the root.
- **One LLM call per reel**, not per segment. Classification-per-segment
  worked but cost more and produced weaker prompts than one holistic pass.
- **No Node.** Remotion was the original renderer; npm is unusable on this
  network (see gotchas). Everything is Python + ffmpeg now.
