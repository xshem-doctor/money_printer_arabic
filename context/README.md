# Project context

Working notes for the Arabic reel generator. Written so a new session (human
or model) can pick up without re-deriving anything.

**Main target:** topic in → finished vertical Arabic reel out, cheap, repeatable,
publishable.

| File | What's in it |
|---|---|
| [architecture.md](architecture.md) | how the pipeline is wired, module by module |
| [status.md](status.md) | what works today, what's half-built, what's missing |
| [gotchas.md](gotchas.md) | hard-won bugs that must not regress — read before editing |
| [roadmap.md](roadmap.md) | what to build next, in order |
| [environment.md](environment.md) | machines, GPU, keys, the network problem |

## One-line summary

`./make_reel.sh "موضوع" name --style gen` produces
`reels/name.mp4` — a 45-55s vertical Arabic reel with generated script,
TTS narration, matched visuals, motion, crossfades, color grade, and
word-chunk captions. Cost per reel: one small DeepSeek call.
