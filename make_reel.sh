#!/bin/bash
# Generate a complete Arabic reel from just a topic.
#
# Usage:
#   ./make_reel.sh "الفائدة المركبة"                        # auto name
#   ./make_reel.sh "لماذا البنوك لا تنام" my_reel           # named output
#   ./make_reel.sh "لماذا البنوك لا تنام" my_reel --addvid  # mix in short stock video cuts
#   ./make_reel.sh "التضخم" infl --style gen                # AI-generated images (ComfyUI)
#   ./make_reel.sh "الادخار" save --girl                    # female narration (Gemini Kore)
#   ./make_reel.sh "الادخار" save --edge                    # original free edge-tts voice
#
# Narration defaults to Gemini "Charon" with an energetic delivery. Override
# with --girl / --edge / --voice, or change the tone with --tts-style.
#
# For --style gen, ComfyUI must be reachable. If it runs on the host machine
# rather than here, start it with --listen 0.0.0.0 and set COMFY_URL, e.g.
#   COMFY_URL=http://10.0.2.2:8188 ./make_reel.sh "التضخم" infl --style gen
#
# Output: reels/<name>.mp4  (vertical 1080x1920, ~45s, narrated + captioned)

set -e
cd "$(dirname "$0")"

TOPIC="${1:?usage: ./make_reel.sh \"topic\" [name] [--addvid|--style gen|...]}"
NAME="${2:-reel_$(date +%Y%m%d_%H%M%S)}"
EXTRA_ARGS=("${@:3}")

SCRIPT_JSON="render/work_${NAME}/script.json"

echo "=== [1/2] writing script (one DeepSeek call) ==="
scene_planner/venv/bin/python scene_planner/write_short.py "$TOPIC" "$SCRIPT_JSON"

echo
echo "=== [2/2] rendering reel ==="
render/venv/bin/python render/build_video.py "$SCRIPT_JSON" "reels/${NAME}.mp4" \
    --chapter-index 0 --target-duration 50 --work-dir "render/work_${NAME}" "${EXTRA_ARGS[@]}"

echo
echo "=== done: reels/${NAME}.mp4 ==="
