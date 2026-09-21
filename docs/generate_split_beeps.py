"""Generates the two beep tone assets bundled with the app for split audio
cues (issue #125). Pure stdlib (wave + struct + math) — no external audio
tooling or downloaded assets, so there's no licensing question and this
script can be re-run to regenerate/tweak the tones.

beep_short.wav: ~150ms, 880Hz (A5) — the base "split changed" beep, and the
building block for the 2-beep/3-beep verdict patterns (played back-to-back
with a short gap by SplitAudioService, not baked into a second asset).

beep_long.wav: ~500ms, 660Hz (E5, a third below the short beep) — the
"back on target" recovery cue. Deliberately a different pitch as well as a
different length, so it's distinguishable even if duration alone is hard to
judge by ear while running.

Both are short sine tones with a linear fade-in/out envelope (avoids the
audible "click" of a hard-edged tone start/stop) at 44.1kHz mono 16-bit PCM.
"""

import math
import struct
import wave

SAMPLE_RATE = 44100


def make_tone(path: str, freq_hz: float, duration_s: float, fade_s: float = 0.01) -> None:
    n_samples = int(SAMPLE_RATE * duration_s)
    fade_samples = int(SAMPLE_RATE * fade_s)
    frames = bytearray()
    for i in range(n_samples):
        t = i / SAMPLE_RATE
        # 0.9, not 0.6: a real device test (S23) found the original 0.6
        # gain, combined with the short 150ms duration, inaudible next to
        # TTS played through the same service — see git log for the full
        # diagnosis (it wasn't a routing bug; the tone was just too quiet).
        amplitude = 0.9
        if i < fade_samples:
            amplitude *= i / fade_samples
        elif i > n_samples - fade_samples:
            amplitude *= (n_samples - i) / fade_samples
        sample = amplitude * math.sin(2 * math.pi * freq_hz * t)
        frames += struct.pack('<h', int(sample * 32767))

    with wave.open(path, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(bytes(frames))


if __name__ == '__main__':
    import sys

    out_dir = sys.argv[1]
    # 0.25s, not 0.15s: longer alongside the louder gain above, so the beep
    # reads as an unmistakable event even briefly heard mid-stride, not just
    # a click.
    make_tone(f'{out_dir}/beep_short.wav', freq_hz=880.0, duration_s=0.25)
    make_tone(f'{out_dir}/beep_long.wav', freq_hz=660.0, duration_s=0.6)
    print('done')
