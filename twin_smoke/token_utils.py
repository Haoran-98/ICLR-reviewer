#!/usr/bin/env python3
"""Token counting with an optional tiktoken fast path."""

from __future__ import annotations


class Utf8HeuristicEncoder:
    name = "utf8_bytes_div_3_conservative"

    def encode_ordinary(self, text: str) -> range:
        # English is usually near four bytes/token and CJK near three, so
        # dividing UTF-8 bytes by three is conservative for this corpus.
        return range((len(text.encode("utf-8")) + 2) // 3)


def get_encoder():
    try:
        import tiktoken
    except ModuleNotFoundError:
        return Utf8HeuristicEncoder()
    return tiktoken.get_encoding("o200k_base")
