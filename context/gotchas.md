# Gotchas

Bugs that cost real time. Read before touching the relevant code.

## Arabic text rendering

**libass scrambles RTL word order with any mid-line override tag.** Karaoke
`{\k}` timing tags and even plain `{\c}` color spans split the line into runs
that get laid out left-to-right, so words appear in the wrong order while each
word's letters look fine. Verified across three workarounds; all failed.

→ Captions must be **plain text**, at most a single tag block at line *start*
(the pop-in `{\fscx70...}` is safe). This is why the style is chunk-flash
rather than karaoke highlight. Don't "improve" it back.

**Pillow ships libraqm.** Draw Arabic with `direction="rtl", language="ar"`
directly. Do *not* also run `arabic_reshaper` / `python-bidi` first — that
double-processes and produces mirrored, disconnected text. (This was the first
Arabic bug; the fix removed those two dependencies entirely.)

## Audio/video sync

Caption timings include `SCENE_PADDING_SEC` per segment, so the **audio track
must carry matching silence gaps** or captions drift ~0.35s per segment
(~2.5s by the end of a reel). `audio_parts` interleaves a generated silence
mp3 between segments for exactly this reason.

Similarly, `xfade` shortens the timeline unless each outgoing clip is
frozen-extended (`tpad`) by the fade duration. Without that, video ends before
audio.

## ffmpeg specifics

- `scale=8000x-1` is invalid; it's `scale=8000:-2` (colon, and `-2` keeps
  dimensions even for libx264).
- Landscape source images need a pre-crop to 9:16 or they letterbox.
- Writing a single frame needs `-update 1`, else ffmpeg wants a `%03d` pattern.
- `concat` demuxer with `-c copy` requires identical encode params across all
  inputs — that's why image clips and video clips use the same encoder flags.

## Pixabay API terms

Responses **must be cached 24h** (their rule, and their media URLs expire in
that window). Implemented in `render/.api_cache/`. Also honour
`X-RateLimit-Reset` on 429, cap `q` at 100 chars, and expect a `large` video
rendition to sometimes have an empty URL — walk down to medium/small/tiny.

There is **no 3D filter in the API** (website only). Image types are
photo/illustration/vector; video types are film/animation.

## This machine's network

**IPv6 is broken.** Node/npm hangs forever on Happy Eyeballs
(`--dns-result-order=ipv4first` is not enough; needs
`--no-network-family-autoselection`). This is why Remotion was abandoned.

**The route to Fastly is bad** (~15-70 kB/s), which is where PyPI serves
wheels. Akamai (pypi.nvidia.com) and CloudFront (HuggingFace) are fine at
~700 kB/s. Workarounds that actually work:

1. `pip install --dry-run --report` to resolve → extract URLs → `aria2c -x16`
   with mirror alternates (tuna/aliyun use identical `/packages/...` paths) →
   `pip install --no-index --find-links`.
2. `pip` has **no resume** for a failed run — completed wheels are only
   committed to cache when the whole download phase succeeds. wget/aria2 do
   resume, so let them fetch and let pip install offline.
3. Ollama and HuggingFace downloads are fine; Ollama's own registry was slow
   for the user, so GGUFs come from HF via `get-model.sh`.

## Script delivery to the user's machine

Files sent via the file-transfer path arrive **with a blank line inserted after
every line**, which breaks backslash line-continuations (`cmd \` + blank line →
orphaned `| grep` → syntax error). Two rules:

- Write shell scripts with **no backslash continuations** — one command per line.
- Prefer delivering via a **quoted heredoc** (`cat > file <<'EOF'`) pasted into
  the terminal; that survives intact. Tarballs (binary) also survive.
- `sed -i 's/\r$//' <file>` after saving, as insurance against CRLF.

## Ollama packaging

Release assets were renamed: it's `ollama-linux-amd64.tar.zst` (zstd), not
`.tgz`. Extract with `tar --zstd -xf`. The `ollama.com/download/...tgz` URL
now 404s after redirect.

## VRAM contention

ComfyUI and Ollama both want the 6GB card. Running both at once OOMs. Stop one,
or rely on Ollama unloading after idle.
