"""Small, dependency-free string similarity: a sounds-alike key and Jaro-Winkler."""

from __future__ import annotations

from functools import lru_cache

_VOWELS = set("AEIOUY")


@lru_cache(maxsize=65536)
def key(token: str) -> str:
    """A consonant skeleton in the spirit of Metaphone: spellings that sound alike agree.

    MUHAMMAD/MOHAMED, KHALID/CHALID, PHILLIPS/FILIPS and SCHMIDT/SHMIDT share keys.
    """

    t = token.upper()
    t = t.replace("X", "KS")  # first, so the X used for SH/CH below is not rewritten
    for a, b in (
        ("SCH", "SK"),
        ("PH", "F"),
        ("GH", "G"),
        ("KH", "K"),
        ("CK", "K"),
        ("SH", "X"),
        ("CH", "X"),
        ("TH", "T"),
        ("DH", "D"),
        ("WR", "R"),
        ("KN", "N"),
        ("DJ", "Y"),
        ("Q", "K"),
        ("Z", "S"),
        ("V", "F"),
        ("W", ""),
        ("J", "Y"),
    ):
        t = t.replace(a, b)
    collapsed: list[str] = []
    for c in t:  # doubled letters only where they stand together
        if not collapsed or collapsed[-1] != c:
            collapsed.append(c)
    t = "".join(collapsed)
    out: list[str] = []
    for i, c in enumerate(t):
        if c == "C":
            c = "S" if i + 1 < len(t) and t[i + 1] in "EIY" else "K"
        if c == "H":
            continue
        if c in _VOWELS:
            if i == 0:
                out.append("A")  # a leading vowel counts, which one does not
            continue
        out.append(c)
    return "".join(out) or t[:1]


@lru_cache(maxsize=262144)
def jaro_winkler(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(len(a), len(b)) // 2 - 1
    flags_a, flags_b = [False] * len(a), [False] * len(b)
    matches = 0
    for i, ca in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not flags_b[j] and b[j] == ca:
                flags_a[i] = flags_b[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    transpositions, k = 0, 0
    for i, ca in enumerate(a):
        if flags_a[i]:
            while not flags_b[k]:
                k += 1
            if ca != b[k]:
                transpositions += 1
            k += 1
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions / 2) / matches) / 3
    prefix = 0
    for ca, cb in zip(a[:4], b[:4], strict=False):
        if ca != cb:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


@lru_cache(maxsize=262144)
def edit_ratio(a: str, b: str) -> float:
    """1 minus the edit distance over the longer length, a swap of neighbours counting once.

    Damerau's (optimal string alignment) distance: the commonest typing slip, two
    letters transposed, costs one edit rather than two.
    """

    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    rows = [list(range(len(b) + 1))]
    for i in range(1, len(a) + 1):
        row = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = a[i - 1] != b[j - 1]
            row[j] = min(rows[i - 1][j] + 1, row[j - 1] + 1, rows[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                row[j] = min(row[j], rows[i - 2][j - 2] + 1)
        rows.append(row)
    return 1 - rows[-1][-1] / max(len(a), len(b))


def letters(token: str) -> str:
    """The word's letters in order: a swap of two letters leaves this unchanged."""

    return "".join(sorted(token))


def trigrams(token: str) -> set[str]:
    padded = f"  {token} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}
