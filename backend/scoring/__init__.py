"""scoring: grade a symbolic performance against a score_to_reference JSON reference.

Zero-latency, sensor-free by design: performance is already a clean note list
(as if from a MIDI keyboard). This is symbolic music alignment (DTW/edit-distance),
not audio or onset detection.
"""
from .config import ScoringConfig
from .midi_io import midi_to_performance
from .score import score_performance

__all__ = ["ScoringConfig", "score_performance", "midi_to_performance"]
