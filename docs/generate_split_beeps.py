"""Generates the beep tone assets bundled with the app for split audio cues
(issue #125). Pure stdlib (wave + struct + math) — no external audio
tooling or downloaded assets, so there's no licensing question and this
script can be re-run to regenerate/tweak the tones.

Four self-contained clips, one per cue, each played with a single
AudioPlayer.play() call — no runtime chaining of repeated plays into a
pattern. That's a deliberate design change (2026-09-21): the original
approach played the same short beep 1/2/3 times back-to-back by calling
play() repeatedly (on one long-lived player, then later on a fresh player
per beep), and on a real device (Samsung S23) the second and third beeps of
a tooFast/tooSlow pattern were silently dropped by the platform layer either
way, despite every individual play() call completing with no error. Baking
the whole pattern into one WAV file removes the runtime chaining entirely —
there is exactly one play() call per cue, so there is nothing left for the
platform to drop.

beep_single.wav:  1 tone,  880Hz (A5) — plain split-changed / start-of-
                  activity beep.
beep_double.wav:  2 tones, 880Hz (A5) — target-verdict "too fast".
beep_triple.wav:  3 tones, 880Hz (A5) — target-verdict "too slow".
beep_long.wav:    1 tone,  660Hz (E5), longer — target-verdict "back on
                  target" ("split time OK again").

The double/triple clips deliberately reuse beep_single's exact tone
(frequency, duration, gain) repeated with a fixed silent gap between
repeats, baked into the file at generation time, rather than being a
distinct sound — the point is the *count*, not a different timbre. The long
clip stays a different pitch and duration (not just "repeat 1") so it's
still tellable apart from a single "too fast"-adjacent beep even by someone
half-listening.
"""

import math
import struct
import wave

SAMPLE_RATE = 44100

# 0.9, not a lower default: a real device test (S23) found an earlier lower
# gain, combined with a short duration, inaudible next to TTS played through
# the same service — see git log for the full diagnosis (it wasn't a
# routing bug; the tone was just too quiet).
_GAIN = 0.9

# 0.25s: long enough to read as an unmistakable event even briefly heard
# mid-stride, not just a click.
_SHORT_TONE_S = 0.25
_LONG_TONE_S = 0.6

# Silent gap baked between repeated tones in the double/triple clips — long
# enough to be heard as separate beeps, short enough that the whole pattern
# stays quick. Matches the runtime gap the old chained-play approach used.
_GAP_S = 0.18


def _tone_samples(freq_hz: float, duration_s: float, fade_s: float = 0.01) -> bytearray:
    n_samples = int(SAMPLE_RATE * duration_s)
    fade_samples = int(SAMPLE_RATE * fade_s)
    frames = bytearray()
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        amplitude = _GAIN
        if i < fade_samples:
            amplitude *= i / fade_samples
        elif i > n_samples - fade_samples:
            amplitude *= (n_samples - i) / fade_samples
        sample = amplitude * math.sin(2 * math.pi * freq_hz * t)
        frames += struct.pack('<h', int(sample * 32767))
    return frames


def _silence_samples(duration_s: float) -> bytearray:
    return bytearray(int(SAMPLE_RATE * duration_s) * 2)  # 2 bytes/sample, all zero


def _write_wav(path: str, frames: bytearray) -> None:
    with wave.open(path, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(bytes(frames))


def make_repeated_tone(path: str, freq_hz: float, duration_s: float, repeats: int) -> None:
    tone = _tone_samples(freq_hz, duration_s)
    gap = _silence_samples(_GAP_S)
    frames = bytearray()
    for i in range(repeats):
        frames += tone
        if i < repeats - 1:
            frames += gap
    _write_wav(path, frames)


if __name__ == '__main__':
    import sys

    out_dir = sys.argv[1]
    make_repeated_tone(f'{out_dir}/beep_single.wav', freq_hz=880.0, duration_s=_SHORT_TONE_S, repeats=1)
    make_repeated_tone(f'{out_dir}/beep_double.wav', freq_hz=880.0, duration_s=_SHORT_TONE_S, repeats=2)
    make_repeated_tone(f'{out_dir}/beep_triple.wav', freq_hz=880.0, duration_s=_SHORT_TONE_S, repeats=3)
    make_repeated_tone(f'{out_dir}/beep_long.wav', freq_hz=660.0, duration_s=_LONG_TONE_S, repeats=1)
    print('done')
