import re
_CANONICAL_CODE_RE = re.compile(r"([A-Za-z]{2,5})[ -]?([0-9]{1,4}[A-Za-z]{0,3})")


def canonical_course_code(code: str) -> str:
    stripped = re.sub(r"[ \t]+", " ", code.strip())
    m = _CANONICAL_CODE_RE.fullmatch(stripped)
    if m:
        return f"{m.group(1).upper()} {m.group(2).upper()}"
    return stripped


