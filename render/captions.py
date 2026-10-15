"""Chunk-flash captions via ASS/libass — a few words at a time, centered,
each chunk replacing the previous with a quick pop-in.

Why this style (and not karaoke highlighting): this libass build splits an
RTL line into separately-ordered runs at EVERY mid-line override tag —
karaoke {\\k} tags and even plain color spans scramble the Arabic word
order (verified empirically). Plain-text lines render perfectly, and a
single tag block at line START wraps the whole line in one run, which is
also safe.

That constraint shapes the emphasis design too: a chunk cannot have one
word coloured. So when a chunk carries the punchy part of a line (a number,
a percentage), the WHOLE chunk switches to the accent style — whole-line
styling is a separate Dialogue event, which is safe.

Word timing is estimated (Microsoft's TTS returns no word boundaries for
Arabic voices): each word gets a slice of the segment's real measured
audio duration proportional to its character length, so chunks stay close
to the narration and never drift across segment boundaries.
"""
import re
from pathlib import Path

WORDS_PER_CHUNK = 3
MAX_CHUNK_CHARS = 28  # keeps a chunk on one line at reel font sizes
POP_MS = 110

# Sentence-ish boundaries, Arabic and Latin. Chunks never span these, so a
# caption can't read "...التداول. تحتاج" across a full stop.
SENTENCE_END = re.compile(r"(?<=[.!?؟:؛])\s+|(?<=،)\s+")

# A chunk containing any of these is the "payoff" of its line and gets the
# accent style: digits (Latin or Arabic-Indic), percent signs, currency.
EMPHASIS = re.compile(r"[0-9٠-٩]|[%٪$€]")

EDGE_PUNCT = ".,!?؟،:؛“”\"'"


def estimate_word_timings(text: str, duration: float) -> list[tuple[str, float, float]]:
    words = text.split()
    if not words:
        return []
    weights = [len(w) + 1 for w in words]
    total = sum(weights)
    timings, t = [], 0.0
    for word, weight in zip(words, weights):
        w_dur = duration * weight / total
        timings.append((word, t, t + w_dur))
        t += w_dur
    return timings


def chunk_words(
    timings: list[tuple[str, float, float]],
    words_per_chunk: int = WORDS_PER_CHUNK,
    max_chars: int = MAX_CHUNK_CHARS,
) -> list[list[tuple[str, float, float]]]:
    """Group timed words into caption chunks that never cross a sentence
    boundary and never overflow one line."""
    chunks: list[list[tuple[str, float, float]]] = []
    current: list[tuple[str, float, float]] = []

    def flush():
        if current:
            chunks.append(current.copy())
            current.clear()

    for item in timings:
        word = item[0]
        prospective = current + [item]
        width = sum(len(w) + 1 for w, _, _ in prospective) - 1

        if current and (len(prospective) > words_per_chunk or width > max_chars):
            flush()
            current.append(item)
        else:
            current.append(item)

        # Break AFTER a word that ends a sentence, so the next clause starts
        # its own caption.
        if word.rstrip(EDGE_PUNCT) != word and re.search(r"[.!?؟:؛،]$", word):
            flush()

    flush()
    return chunks


def _fmt_time(seconds: float) -> str:
    cs = round(seconds * 100)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# Two styles, identical geometry, different colour. Switching style per
# event is safe for RTL; switching colour mid-line is not.
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Flash,Noto Sans Arabic,{fontsize},&H00FFFFFF,&H000000FF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,60,60,{marginv},1
Style: Punch,Noto Sans Arabic,{punch_size},&H0043D6FF,&H000000FF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

POP_TAG = f"{{\\fscx78\\fscy78\\t(0,{POP_MS},\\fscx100\\fscy100)}}"


def build_ass(
    segments_with_offset: list[tuple[dict, float, float]],
    out_path: Path,
    width: int,
    height: int,
    fontsize: int | None = None,
    marginv: int | None = None,
    words_per_chunk: int = WORDS_PER_CHUNK,
    plate: bool = False,
    emphasis: bool = True,
):
    """segments_with_offset: list of (segment_dict, global_start_sec, duration_sec).

    fontsize/marginv default to a proportion of the frame so the captions
    look the same on any output size.
    """
    # ~6% of frame height reads well on a phone; the old 76px on 1920 was ~4%.
    fontsize = fontsize or max(48, round(height * 0.062))
    punch_size = round(fontsize * 1.12)
    marginv = marginv if marginv is not None else round(height * 0.17)
    outline = max(3, round(fontsize * 0.075))
    # BorderStyle 3 draws an opaque box (the "plate"); 1 is outline + shadow.
    border_style = 3 if plate else 1
    shadow = 0 if plate else max(1, round(fontsize * 0.02))

    lines = [
        ASS_HEADER.format(
            width=width,
            height=height,
            fontsize=fontsize,
            punch_size=punch_size,
            marginv=marginv,
            outline=outline,
            shadow=shadow,
            border_style=border_style,
        )
    ]

    for seg, global_start, duration in segments_with_offset:
        if seg["scene"] == "title_card":
            continue  # title cards carry their own big baked-in text
        timings = estimate_word_timings(seg["text"], duration)
        for chunk in chunk_words(timings, words_per_chunk):
            start = global_start + chunk[0][1]
            end = global_start + chunk[-1][2]
            raw = " ".join(word for word, _, _ in chunk)
            # strip edge punctuation: at flash pace it adds nothing, and mixed
            # bidi pushes trailing marks to the wrong side of the chunk
            text = raw.strip(EDGE_PUNCT).strip()
            if not text:
                continue
            style = "Punch" if (emphasis and EMPHASIS.search(text)) else "Flash"
            lines.append(
                f"Dialogue: 0,{_fmt_time(start)},{_fmt_time(end)},{style},,0,0,0,,{POP_TAG}{text}\n"
            )

    out_path.write_text("".join(lines), encoding="utf-8")
