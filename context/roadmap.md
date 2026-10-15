# Roadmap

Ordered by impact on the main target: **publishable reels, reliably.**

## 1. Move the pipeline to the laptop  ← unblocks everything

The GPU is there; the sandbox can't reach it. A packaged version exists
(self-contained folder, own venv, own ffmpeg, `rm -rf` uninstall) but hasn't
been installed yet.

Needs: `pacman -S ffmpeg aria2`, copy the project, run `setup.sh`, move keys.
After this, `--style gen` works in one command and the two-machine problem
disappears permanently.

## 2. Fix image↔script relevance  ← top quality complaint

The user's standing objection: *"the images are not fully related to the video
script."* Candidate fixes, cheapest first:

- Tighten `image_prompt` instructions: force a concrete subject + action +
  setting, ban abstractions, require the segment's key noun to appear.
- Feed the *previous* segment's prompt into the next so the thread is explicit
  rather than implied by `visual_theme`.
- Generate 2-3 candidates per segment and pick by CLIP similarity to the
  prompt (needs a small extra model, but fully local).
- Let the script writer name a recurring character sheet once, then reference
  it by short tag per segment.

## 3. Restore `counter_scene` / `list_scene` visuals

Both scene types still classify correctly but render as ordinary image + caption.
Bring back the big animated number and the staggered bullet list as PIL overlays
composited over the generated image, timed to the segment.

## 4. Consistent house style

A LoRA (or a fixed style suffix + fixed sampler settings + seed discipline)
so every reel in a series looks like the same channel. This is what separates
"AI slop" from a recognisable brand.

## 5. Motion beyond Ken Burns

AnimateDiff at 512px fits 6 GB and gives 2-4s of real motion per shot. Use it
for the hook segment first (highest retention value), keep stills elsewhere to
control render time.

## 6. Music + sound design

Populate `render/assets/music/` from Pixabay Music / YouTube Audio Library.
Then: duck under narration (already implemented), and consider a whoosh on
segment transitions.

## 7. Publishing

Nothing built. Eventually: thumbnail/cover frame, title + description
generation (same DeepSeek call), and upload automation per platform.

---

## Parallel track: `aichat`

Pending fixes before it's genuinely pleasant:
- render markdown (`###`, `**bold**`, `` `inline` ``) instead of showing raw
- `/copy` fallback when no clipboard tool: write the block to a file and print
  the path (currently just errors)
- dedent code blocks that were indented inside list items

Then the agent extension: a `tools` module (read_file, write_file, run_command)
plus a loop feeding tool results back as messages. The `Provider` trait already
streams, and `Session` is UI-independent, so both seams are ready.
