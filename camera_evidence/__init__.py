"""camera_evidence: cross-validates scoring/'s result.json against an
independent camera-based fingertip-position evidence source, to resolve
octave errors that audio alone can't disambiguate -- see cross_validate.py
for why (harmonics vs. physical key position).

No camera hardware is available yet: calibration.py and
fingertip_source.SyntheticFingertipSource let this be built and tested now;
fingertip_source.MediaPipeFingertipSource is a stub for the real
implementation later.
"""
from .calibration import calibrate, load_calibration, pixel_to_pitch, pitch_to_pixel, save_calibration
from .config import CameraEvidenceConfig
from .cross_validate import apply_camera_evidence
from .fingertip_source import FingertipSource, MediaPipeFingertipSource, SyntheticFingertipSource

__all__ = [
    "CameraEvidenceConfig",
    "apply_camera_evidence",
    "FingertipSource",
    "SyntheticFingertipSource",
    "MediaPipeFingertipSource",
    "calibrate",
    "save_calibration",
    "load_calibration",
    "pixel_to_pitch",
    "pitch_to_pixel",
]
