from __future__ import annotations

import re
import unicodedata


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).casefold()
    text = text.replace("0", "o")
    text = re.sub(r"[^0-9a-z가-힣]+", " ", text)
    stopwords = {
        "ctf",
        "contest",
        "online",
        "offline",
        "qual",
        "quals",
        "qualifier",
        "qualifiers",
        "final",
        "finals",
        "prelim",
        "prelims",
        "preliminary",
    }
    tokens = []
    for token in text.split():
        if token in stopwords:
            continue
        if re.fullmatch(r"20\d{2}", token):
            continue
        tokens.append(token)
    return " ".join(tokens)


def titles_overlap(left: str, right: str) -> bool:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if left_normalized in right_normalized or right_normalized in left_normalized:
        return min(len(left_normalized), len(right_normalized)) >= 6

    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    if not left_tokens or not right_tokens:
        return False

    overlap = left_tokens & right_tokens
    if not overlap:
        return False

    similarity = len(overlap) / max(len(left_tokens), len(right_tokens))
    if len(overlap) >= 2 and similarity >= 0.67:
        return True
    return len(overlap) == 1 and len(left_tokens) == 1 and len(right_tokens) == 1
