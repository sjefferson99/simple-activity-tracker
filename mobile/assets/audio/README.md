# Split audio cue tones (issue #125)

`beep_short.wav` and `beep_long.wav` are generated tones, not sourced/licensed audio —
see the generator script kept at `docs/generate_split_beeps.py` in the repo root's
`docs/` folder. Re-run it with an output directory argument to regenerate or tweak them
(frequency/duration/fade), e.g.:

```
python3 docs/generate_split_beeps.py mobile/assets/audio
```

- `beep_short.wav` — ~250ms, 880Hz (A5), gain 0.9. The base "split changed" cue, and also
  the building block `SplitAudioService` plays back-to-back (with a short gap) for the
  2-beep (too fast) / 3-beep (too slow) verdict patterns — there is no separate asset per
  beep count.
- `beep_long.wav` — ~600ms, 660Hz (E5), gain 0.9. The single "back on target" recovery
  cue — deliberately a different pitch as well as longer, so it's distinguishable by ear
  even when duration alone is hard to judge while running.

Originally 150ms/500ms at gain 0.6 — lengthened and made louder after a real device test
(S23) found the beep technically played (confirmed in logcat) but was inaudible next to
TTS spoken through the same service.
