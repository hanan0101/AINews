"""Small, dependency-free conversions shared outside the pipeline."""


def safe_int(value, default=0):
    """Convert a value to ``int`` and return ``default`` on invalid input."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default

