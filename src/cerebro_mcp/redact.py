"""Sensitive-line redaction, applied to every file before it is parsed.

A line that looks like it carries a secret, a card or bank number, or (with the
optional `mx` pack) a Mexican national ID is replaced, whole, by a placeholder
such as `[redacted:secret]`: line numbers of checkboxes stay right and the value
never reaches the index. The reasons say *what kind* of value was found, never the value.

The detectors are conservative on purpose: a false positive costs one blank
line in search results; a false negative puts a credential into an MCP client.
"""

from __future__ import annotations

import re
from collections.abc import Callable

# A file with at least this many redacted lines is treated as private.
LINES_TO_MAKE_PRIVATE = 5

# ---------- secrets ----------

_SECRETS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),  # Google API key
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[0-9A-Za-z]{10,}"),  # Stripe-style keys
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}"),  # OpenAI / Anthropic-style keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"\"private_key\"\s*:"),
    re.compile(r"\b[a-z][a-z0-9+.\-]*://[^\s:/@]+:[^\s/@]{3,}@"),  # credentials inside a URL
    # KEY=value / password: value assignments with a long opaque value.
    re.compile(
        r"(?i)\b[\w.\-]*(?:api[_\-]?key|secret|token|passw(?:or)?d|passwd|access[_\-]?key|client[_\-]?secret)"
        r"[\w.\-]*\b[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_\-./+=]{12,}"
    ),
)


def _secrets(line: str) -> bool:
    return any(p.search(line) for p in _SECRETS)


# ---------- cards and bank accounts ----------

# Test numbers published by payment providers: not anyone's card.
_TEST_CARDS = frozenset(
    {"4242424242424242", "4000056655665556", "5555555555554444", "4000000000003220", "378282246310005"}
)
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
_LABELLED_ACCOUNT = re.compile(
    r"(?i)\b(?:account (?:number|no\.?)|acct\.?|card(?: number)?|n[uú]mero de cuenta|no\.? de cuenta|"
    r"cuenta bancaria|tarjeta|routing(?: number)?)\b\W{0,12}(\d[\d -]{6,}\d)"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")


def _luhn(digits: str) -> bool:
    total, double = 0, False
    for c in reversed(digits):
        d = int(c)
        if double:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        double = not double
    return total % 10 == 0


def _iban_ok(value: str) -> bool:
    compact = value.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def _cards(line: str) -> bool:
    for m in _LABELLED_ACCOUNT.finditer(line):
        if re.sub(r"\D", "", m.group(1)) not in _TEST_CARDS:
            return True
    for m in _CARD.finditer(line):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and digits not in _TEST_CARDS:
            return True
    return any(_iban_ok(m.group(0)) for m in _IBAN.finditer(line))


# ---------- Mexico (optional pack) ----------

_CURP = re.compile(r"\b[A-Z][AEIOUX][A-Z]{2}\d{6}[HMX][A-Z]{5}[A-Z0-9]\d\b", re.IGNORECASE)
_RFC = re.compile(r"\b[A-ZÑ&]{3,4}\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[A-Z\d]{2}[A\d]\b")
_RFC_GENERIC = frozenset({"XAXX010101000", "XEXX010101000"})  # SAT placeholders, not a person
_CLABE = re.compile(r"(?<![\d.])\d{3}[ -]?\d{3}[ -]?\d{11}[ -]?\d(?![\d.])")
_CLABE_LABEL = re.compile(r"(?i)\bclabe\b\W{0,12}\d{4,}")
_INE_KEY = re.compile(r"\b[A-Z]{6}\d{8}[HM]\d{3}\b")
_INE_MRZ = re.compile(r"(?i)\bIDMEX\d{6,}")
_INE_LABEL = re.compile(
    r"(?i)\b(?:ine|ife|credencial de elector|clave de elector|cic|ocr)\b\W{0,12}(?=(?:[A-Z]*\d){4})[A-Z0-9]{9,}\b"
)


def _mx(line: str) -> bool:
    if _CURP.search(line):
        return True
    if any(m.group(0) not in _RFC_GENERIC for m in _RFC.finditer(line)):
        return True
    if _CLABE.search(line) or _CLABE_LABEL.search(line):
        return True
    return bool(_INE_KEY.search(line) or _INE_MRZ.search(line) or _INE_LABEL.search(line))


PACKS: dict[str, tuple[str, str, Callable[[str], bool]]] = {
    # pack name: (placeholder label, human reason, detector)
    "secrets": ("secret", "secret or credential", _secrets),
    "cards": ("card", "card or bank account number", _cards),
    "mx": ("mx", "Mexican ID or bank number (CLABE/RFC/CURP/INE)", _mx),
}


def matching_packs(line: str, packs: tuple[str, ...] | list[str]) -> list[str]:
    return [p for p in packs if p in PACKS and PACKS[p][2](line)]


def reasons(line: str, packs: tuple[str, ...] | list[str]) -> list[str]:
    """Which kinds of sensitive value `line` seems to carry (never the value itself)."""
    return [PACKS[p][1] for p in matching_packs(line, packs)]


def placeholder(pack: str) -> str:
    return f"[redacted:{PACKS[pack][0]}]"


def redact(text: str, packs: tuple[str, ...] | list[str]) -> tuple[str, int, list[str]]:
    """Replace every sensitive line with `[redacted:<kind>]`.

    Inside the YAML frontmatter the placeholder is written as a YAML comment so
    the rest of the frontmatter still parses. Returns the cleaned text (same
    number of lines), how many lines were redacted and the distinct reasons.
    """
    if not packs:
        return text, 0, []
    from .notes import frontmatter_span

    span = frontmatter_span(text.replace("\r\n", "\n"))
    lines = text.split("\n")
    redacted = 0
    found: dict[str, None] = {}
    for i, line in enumerate(lines):
        hit = matching_packs(line, packs)
        if not hit:
            continue
        mark = placeholder(hit[0])
        if span and span[0] <= i <= span[1]:
            mark = "# " + mark
        lines[i] = mark
        redacted += 1
        found.update(dict.fromkeys(PACKS[p][1] for p in hit))
    return "\n".join(lines), redacted, list(found)
