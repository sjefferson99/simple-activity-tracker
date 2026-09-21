# Split audio cue tones (issue #125)

Four generated tones, not sourced/licensed audio — see the generator script kept at
`docs/generate_split_beeps.py` in the repo root's `docs/` folder. Re-run it with an output
directory argument to regenerate or tweak them (frequency/duration/gain/gap), e.g.:

```
python3 docs/generate_split_beeps.py mobile/assets/audio
```

Each is a **self-contained clip played with a single `AudioPlayer.play()` call** — the
double/triple-beep patterns are baked into the WAV file at generation time, not produced
by calling `play()` repeatedly at runtime. That's a deliberate design change (2026-09-21):
the original approach chained repeated plays of one short beep into a pattern, and on a
real device (Samsung S23) the second and third beeps were silently dropped by the
platform layer regardless of whether one long-lived `AudioPlayer` or a fresh instance per
beep was used — every individual `play()` call completed with no error, but only the
first beep of a pattern was ever audible. Baking the whole pattern into one file removes
the runtime chaining entirely, so there's nothing left for the platform to drop.

- `beep_single.wav` — one 0.25s, 880Hz (A5) tone. The "split changed" / start-of-activity
  cue, and the too-fast/too-slow patterns' building-block tone (repeated, not reused via
  a second play() call — see above).
- `beep_double.wav` — the same tone twice, 0.18s of silence between. Target-verdict "too
  fast".
- `beep_triple.wav` — the same tone three times, 0.18s of silence between. Target-verdict
  "too slow".
- `beep_long.wav` — one 0.6s, 660Hz (E5) tone — deliberately a different pitch as well as
  duration from the others, so it reads as a genuinely different event. Target-verdict
  "back on target" ("split time OK again").
