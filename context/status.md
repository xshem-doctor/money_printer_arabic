# Status

Last updated: 2026-09-08

## Works end to end

- **Script generation** — DeepSeek writes hook/segments/payoff with a shared
  visual theme and per-segment image prompts. Quality is good.
- **Narration** — edge-tts, `ar-EG-ShakirNeural` (user-picked from a 3-voice
  A/B). Free, no key.
- **Stock visuals** — `--style real` (Pexels→Pixabay) and `--style draw`
  (Pixabay illustrations/vectors/animation). Credits manifest per reel.
- **Generated visuals** — `--style gen` via ComfyUI, when reachable.
- **Motion + assembly** — Ken Burns variants, crossfades, color grade, grain,
  vignette, optional music bed, chunk-flash Arabic captions.
- **Resumability + logging** — every phase timestamped, `build.log` per run,
  re-run continues instead of restarting.

Reels produced so far live in `reels/` with their `.credits.json`.

## Half-built / known weak

- **Image-to-script relevance.** The user's words: *"the images are not fully
  related to the video script."* Generation helps but prompts still drift.
  This is the top quality issue.
- **`counter_scene` / `list_scene` are cosmetic.** The renderer picks images
  for them but no longer draws the big animated number or the bulleted list —
  the old overlay system was replaced by chunk-flash captions and never
  reinstated.
- **Music folder is empty.** `render/assets/music/` has only a README; reels
  render silent-bed until tracks are added.
- **No `--style gen` from this VM.** ComfyUI runs on the laptop; this sandbox
  is a different machine behind NAT (see environment.md). Generation works when
  run on the laptop.

## Not started

- Moving the pipeline onto the laptop (packaged, tested, but not installed).
- Animating stills (AnimateDiff / SVD) instead of Ken Burns.
- LoRA-based house style for perfectly consistent looks.
- Any publishing/upload automation.

## Side projects (support the main target)

- **`~/ai-images/`** — ComfyUI + DreamShaper 8 on the RTX 4050. Working.
  `gen.py` generates images from the CLI.
- **`~/ai-llm/`** — Ollama + Qwen2.5-Coder-7B (Q4_K_M), full GPU offload
  confirmed (29/29 layers). Working.
- **`aichat`** — Rust terminal chat client for Ollama + DeepSeek. Compiles and
  tested against a mock server. Pending fixes: markdown rendering (`###`,
  `**bold**` show raw) and a `/copy` fallback when no clipboard tool exists.
