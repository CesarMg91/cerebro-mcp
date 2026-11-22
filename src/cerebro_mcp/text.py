"""Small text helpers shared by every module."""

from __future__ import annotations

import hashlib
import re
import unicodedata

WORD = re.compile(r"\w+", re.UNICODE)

# Words that carry no meaning for lexical matching (English and Spanish).
STOPWORDS = frozenset(
    """
    a about after again all also am an and any are as at be because been before being
    but by can could did do does doing done for from had has have having he her here hers
    him his how i if in into is it its just me more most my no nor not now of off on once
    only or other our out over own same she should so some such than that the their them
    then there these they this those through to too under until up very was we were what
    when where which while who whom why will with would you your
    al algo algun alguna como con cual cuando de del desde donde e el ella ellas ellos en
    entre era es esa ese eso esta este esto fue ha han hay la las le les lo los mas me mi
    mis muy nada ni o otra otro para pero por porque que se si sin sobre su sus te tu tus
    un una uno unos unas y ya yo
    """.split()
)


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def fold(value: str) -> str:
    """Lowercase without accents, for comparing names."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_tokens(value: str) -> list[str]:
    """Folded words without stopwords and one-letter tokens."""
    return [t for t in WORD.findall(fold(value)) if len(t) > 1 and t not in STOPWORDS]


def stem(token: str) -> str:
    """A deliberately tiny plural stripper (ads -> ad, dias -> dia, meses -> mes)."""
    if len(token) > 4 and (token.endswith(("ches", "shes")) or (token.endswith("es") and token[-3] in "sxzn")):
        return token[:-2]
    if len(token) > 2 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token
