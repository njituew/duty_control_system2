"""Парсер номера т/с из строки. Зашарил почему они в РБ разных форматов, дзякуй."""

import re

_DIGIT_GROUP_RE = re.compile(r"\d+")


def _letter_glued_split(raw: str, run_start: int, run_end: int, run: str) -> str | None:
    """Разбить слитую мину из 5 цифр (номер + код региона) на сам номер.

    Если цифры и буквы идут подряд без разделителя, определить, на каком
    конце «прилип» код региона. Возвращает 4-значный номер или None, если
    соседствует с буквами с обеих сторон (неоднозначно).
    """
    before = raw[run_start - 1] if run_start > 0 else ""
    after = raw[run_end] if run_end < len(raw) else ""

    if after.isalpha() and not before.isalpha():
        return run[-4:]  # регион в начале, буквы после: "10010PC" -> "0010"
    if before.isalpha() and not after.isalpha():
        return run[:4]  # буквы до, регион в конце: "PC00101" -> "0010"
    return None


def normalize_plate_number(raw: str) -> str | None:
    """Извлечь основной 4-значный номер из строки знака; None, если цифр нет."""
    if not raw:
        return None

    matches = list(_DIGIT_GROUP_RE.finditer(raw))

    for m in matches:
        if len(m.group()) == 4:
            return m.group()

    for m in matches:
        if len(m.group()) == 5:
            split = _letter_glued_split(raw, m.start(), m.end(), m.group())
            if split:
                return split

    longest = max((m.group() for m in matches), key=len, default=None)
    return longest
