"""ReDeck Style Pattern Library — deck-consistent design injection."""

from .selector import select_pattern_for_deck, get_pattern_by_name
from .injector import format_deck_style_contract
from .vocab_composer import compose_style_elements, format_vocab_style_contract

__all__ = [
    "select_pattern_for_deck",
    "get_pattern_by_name",
    "format_deck_style_contract",
    "compose_style_elements",
    "format_vocab_style_contract",
]
