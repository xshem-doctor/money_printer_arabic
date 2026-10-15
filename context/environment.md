# Environment

## Machines

There are **two separate machines**, and this matters constantly.

### Laptop (`archlinux`, the real workstation)
- Arch Linux, kernel 7.1.8-arch1-3, Python 3.14.7, bash
- CPU: AMD Ryzen 7 7445HS · RAM: 31 GB
- GPU: **NVIDIA RTX 4050 Laptop, 6 GB** (driver 610.57.04, CUDA 13.3)
  plus an AMD Radeon 740M iGPU driving the display (hybrid — normal)
- Runs: ComfyUI (`~/ai-images/`), Ollama (`~/ai-llm/`)
- i3 + polybar (a GPU module was added: `~/.config/polybar/gpu.sh`)

### Sandbox VM (where these sessions run)
- Debian-ish, Python 3.13, no GPU, 4 cores, 15 GB RAM
- IP `10.0.2.15` behind QEMU-style NAT, plus a VPN tun0, public IP differs
  from the laptop's → **cannot reach the laptop's services**. `10.0.2.2:8188`
  was tested and is unreachable.
- Holds the reels pipeline source (`~/Desktop/vidoprojects`)

**Consequence:** `--style gen` can't run from the sandbox. Either move the
pipeline to the laptop (packaged, recommended) or tunnel ComfyUI out
(cloudflared). Decision was **move to laptop**; not yet installed.

## Isolation convention

Every tool lives in one folder, deletable with a single `rm -rf`:

```
~/ai-images/     ComfyUI + models + venv + caches   (rm -rf ~/ai-images)
~/ai-llm/        Ollama + GGUFs + aichat + caches   (rm -rf ~/ai-llm)
~/aichat/        Rust source for the chat client
```

Nothing installed system-wide except the NVIDIA driver, ffmpeg, aria2, zstd —
all general-purpose. Node lives at `~/.local/opt/node/bin` (unused now).

## Keys

All in `scene_planner/.env` (chmod-sensitive, never commit):

```
DEEPSEEK_API_KEY=    script generation (required)
GEMINI_API_KEY=      narration (default voice; falls back to edge-tts if absent)
PEXELS_API_KEY=      --style real
PIXABAY_API_KEY=     --style draw + fallback
```

`aichat` stores its DeepSeek key separately in `aichat-data/config.json` (0600).

## Models on the laptop

| Where | Model | Notes |
|---|---|---|
| ComfyUI | DreamShaper 8 (SD 1.5) | 2.1 GB, flat-illustration capable |
| Ollama | Qwen2.5-Coder-7B-Instruct Q4_K_M | 4.4 GB, 29/29 layers on GPU |

Sweet spot for 6 GB is 7-8B at Q4_K_M. `Q5_K_M` and above will spill to RAM.

## Licensing posture

- Scripts are generated (original), not translated from someone's video.
- Stock is Pexels/Pixabay only — both allow commercial use without attribution;
  every asset is logged to `reels/<name>.credits.json`.
- SD 1.5 fine-tunes are open-weights, commercial use OK. Avoid Flux *dev* and
  SANA (non-commercial).
- Music must come from the vetted local folder — never platform trending audio.
- edge-tts uses Microsoft's endpoint unofficially; for serious monetization
  switch to paid Azure TTS or ElevenLabs (same interface, one line).
