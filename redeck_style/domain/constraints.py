"""Shared rendering requirements for planning, prompts and diagnostics."""

MIN_BODY_PX = 15
MIN_LABEL_PX = 11
MIN_TEXT_CONTRAST = 4.5
FRAGMENT_SHORT_EDGE = 32
FRAGMENT_LONG_EDGE = 256
FRAGMENT_ASPECT_RATIO = 12


def title_size_ceiling(role, title_length):
    if role == "title":
        return 42 if title_length > 80 else 52
    if title_length > 92:
        return 38
    if title_length > 80:
        return 42
    return 44 if title_length > 68 else 50
