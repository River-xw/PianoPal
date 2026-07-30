# English posture voice cues

These short WAV files are played by `LiveSession.jsx` when the Raspberry Pi
publishes a persistent posture issue through `/api/session/status`.

| File | Classifier label | Spoken prompt |
| --- | --- | --- |
| `curve-fingers.wav` | `finger_collapse` | Keep your fingers gently curved. |
| `fingers-close.wav` | `high_lift_tap` | Keep your fingers close to the keys. |
| `lower-wrist.wav` | `wrist_arch` | Lower your wrist and keep it relaxed. |
| `neutral-wrist.wav` | `wrist_collapse` | Lift your wrist into a neutral position. |
| `steady-wrist.wav` | `wrist_shake` | Steady your wrist and relax your hand. |

The assets are mono 22.05 kHz, 16-bit PCM WAV files. The cue mapping and
anti-spam policy live in `edge/posture_feedback.py`.
