"""Generate segment images with a local ComfyUI instance instead of fetching
stock media.

Mirrors stock_media's role in the pipeline: given a prompt and a count, return
image bytes. ComfyUI serves the finished PNGs over the same HTTP API used to
queue the job, so this works across machines — the renderer can run here while
the GPU runs on another host (set COMFY_URL).

Consistency across a reel comes from three things, all applied here:
  - one visual_theme string (character + palette) appended to every prompt
  - one fixed style suffix
  - a per-reel base seed, offset per segment (reproducible, but not identical)
"""
import json
import os
import time
import urllib.parse
import urllib.request

DEFAULT_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
DEFAULT_CKPT = os.environ.get("COMFY_CKPT", "dreamshaper8.safetensors")

STYLE_SUFFIX = ("flat vector illustration, minimal geometric shapes, bold flat colors, "
                "clean simple background, modern infographic style, crisp edges, "
                "consistent art style")
NEGATIVE = ("photo, photorealistic, 3d render, text, letters, words, watermark, "
            "signature, blurry, grainy, deformed hands, extra fingers, extra limbs, "
            "ugly, cluttered, busy background")

LICENSE_NOTE = ("Generated locally with Stable Diffusion 1.5 fine-tune "
                "(open weights, commercial use permitted)")


def _post(url: str, path: str, payload: dict, timeout: int = 30):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{url}{path}", data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get(url: str, path: str, timeout: int = 30) -> bytes:
    with urllib.request.urlopen(f"{url}{path}", timeout=timeout) as resp:
        return resp.read()


def is_available(url: str = DEFAULT_URL, timeout: int = 5) -> bool:
    try:
        _get(url, "/system_stats", timeout=timeout)
        return True
    except Exception:
        return False


def build_workflow(prompt, negative, width, height, batch, steps, cfg, seed, ckpt):
    return {
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
            "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["5", 0]}},
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {
            "width": width, "height": height, "batch_size": batch}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "reel", "images": ["8", 0]}},
    }


def generate(prompt: str, count: int, seed: int, url: str = DEFAULT_URL,
             width: int = 512, height: int = 768, steps: int = 25, cfg: float = 7.0,
             ckpt: str = DEFAULT_CKPT, theme: str = "", timeout: int = 900,
             log=print) -> list[bytes]:
    """Queue one batch and return the finished PNGs as bytes.

    Raises on failure — the caller decides whether to fall back to stock.
    """
    parts = [p for p in (prompt, theme, STYLE_SUFFIX) if p]
    full_prompt = ", ".join(parts)

    workflow = build_workflow(full_prompt, NEGATIVE, width, height,
                              count, steps, cfg, seed, ckpt)
    resp = _post(url, "/prompt", {"prompt": workflow, "client_id": f"reels-{seed}"})
    prompt_id = resp["prompt_id"]

    start = time.time()
    outputs = None
    while time.time() - start < timeout:
        history = json.loads(_get(url, f"/history/{prompt_id}"))
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise RuntimeError(f"ComfyUI reported an error: {status}")
            outputs = entry.get("outputs", {})
            if outputs:
                break
        time.sleep(1.5)

    if not outputs:
        raise TimeoutError(f"ComfyUI produced nothing after {timeout}s")

    images: list[bytes] = []
    for node_output in outputs.values():
        for info in node_output.get("images", []):
            q = urllib.parse.urlencode({
                "filename": info["filename"],
                "subfolder": info.get("subfolder", ""),
                "type": info.get("type", "output"),
            })
            images.append(_get(url, f"/view?{q}", timeout=120))
    return images
