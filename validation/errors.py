"""Typed errors for the validation module."""


class ValidationError(Exception):
    """Base class for all validation errors."""


class SynthesisError(ValidationError):
    """Raised when reference MIDI -> audio synthesis can't proceed reliably.

    Deliberately raised (never silently worked around with a sine-wave
    substitute) when a real piano soundfont isn't available -- see synth.py.
    """
