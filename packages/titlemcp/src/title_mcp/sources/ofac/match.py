"""The screening engine: an index over several name keys, and an examiner-like score.

Every listed name and alias is indexed by its canonical words, their sounds-alike
keys and character trigrams, so a party's name pulls candidates however it was
spelled. Each candidate is then scored by aligning words to words (order, missing
middle names, initials and joined names tolerated), weighting each word by how
common it is in the United States, and adjusting for OFAC's weak-alias flag,
entity type and date of birth. Each adjustment is written down as a reason.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from title_mcp.sources.ofac import frequency, phonetic
from title_mcp.sources.ofac.models import (
    AliasQuality,
    Candidate,
    EntryType,
    Outcome,
    PartyScreening,
    PartyType,
    SanctionsEntry,
    ScreeningParty,
)
from title_mcp.sources.ofac.normalize import ENTITY_SUFFIXES, fold, tokens, unprefixed

#: Marks a word made by joining two (ABDUL+RAHMAN): compared by edit distance only.
JOIN = "+"


@dataclass(frozen=True)
class Thresholds:
    potential_match: float = 0.86
    likely_false_positive: float = 0.72
    #: Below this, a partial match on common words alone cannot be a potential match.
    anchor_weight: float = 0.55
    #: A match on only part of a listed name, or crosswise and inexact, needs a word
    #: at least this rare (most U.S. surnames weigh less).
    partial_anchor_weight: float = 0.8
    #: A listed name covered less than this is a partial match.
    partial_name_cover: float = 0.75
    max_candidates: int = 10

    def as_dict(self) -> dict[str, float]:
        return {
            "potential_match": self.potential_match,
            "likely_false_positive": self.likely_false_positive,
            "anchor_weight": self.anchor_weight,
        }


@dataclass
class _Form:
    entry: int
    name: int
    tokens: list[str]
    weights: list[float]
    keys: list[str]


@dataclass
class _Alignment:
    score: float
    query_cover: float
    name_cover: float
    pairs: list[tuple[str, str, float]] = field(default_factory=list)
    anchor: float = 0.0
    #: The words line up only in a different order, and not all exactly.
    crosswise_inexact: bool = False
    anchor_if_crosswise: float = 0.0
    crosswise: bool = False
    all_exact: bool = False
    any_exact: bool = False
    distinctive_query_words: int = 0
    best_distinctive: float = 0.0


def _is_entity(entry_type: EntryType) -> bool:
    return entry_type is not EntryType.INDIVIDUAL


def _looks_like_entity(name: str) -> bool:
    words = fold(name).split()
    return any(w in ENTITY_SUFFIXES for w in words[1:]) or bool(
        re.search(r"\bL\.?L\.?C\b", name.upper())
    )


def token_similarity(a: str, b: str, entity: bool = False) -> float:
    """How alike two words are, 0 to 1, allowing either an attached AL-/EL- prefix."""

    best = _similarity(a, b, entity)
    if best < 1.0:
        for x, y in ((unprefixed(a), b), (a, unprefixed(b))):
            if x and y:
                best = max(best, _similarity(x, y, entity))
    return best


def _similarity(a: str, b: str, entity: bool) -> float:
    if JOIN in a or JOIN in b:
        # A joined word is compared whole and strictly: JOHN+DOE is not JOHN+LEE.
        a, b = a.replace(JOIN, ""), b.replace(JOIN, "")
        if a == b:
            return 1.0
        ratio = phonetic.edit_ratio(a, b)
        return ratio if ratio >= 0.85 else 0.0
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:
        # An initial stands for a person's name; a lone letter in a company name is noise.
        return 0.75 if not entity and a[0] == b[0] else 0.0
    if min(len(a), len(b)) / max(len(a), len(b)) < 0.65:
        return 0.0  # a shared beginning is not a shared name: BLUEOX is not BLU
    if max(len(a), len(b)) >= 8:
        # Long words (and joined ones) by edit distance: Jaro-Winkler rewards a long
        # shared beginning, which would make a joined name look like a longer, different one.
        ratio = phonetic.edit_ratio(a, b)
        return ratio if ratio >= 0.85 else 0.0
    jw = phonetic.jaro_winkler(a, b)
    key = phonetic.key(a)
    if len(key) >= 3 and key == phonetic.key(b) and jw >= 0.80:  # a 2-letter key says little
        return max(0.92, jw)
    return jw if jw >= 0.88 else 0.0


def _joined(
    words: list[str], weights: list[float], entity: bool = False
) -> list[tuple[list[str], list[float]]]:
    """The words as given, and with each adjacent pair joined (ABDUL RAHMAN -> ABDULRAHMAN).

    A joined word weighs what its parts did together, so two generic words stay weak.
    """

    shapes = [(words, weights)]
    for i in range(len(words) - 1):
        if len(words[i]) == 1 or len(words[i + 1]) == 1:
            continue  # an initial is not half of a name: JOHN M is not JOHNM
        if entity and min(weights[i], weights[i + 1]) <= 0.5:
            continue  # nor is a business word or an initialism: RJB HOLDING is not one word
        shapes.append(
            (
                [*words[:i], words[i] + JOIN + words[i + 1], *words[i + 2 :]],
                [*weights[:i], min(1.0, weights[i] + weights[i + 1]), *weights[i + 2 :]],
            )
        )
    return shapes


def align(
    query: list[str],
    query_weights: list[float],
    name: list[str],
    name_weights: list[float],
    entity: bool = False,
) -> _Alignment:
    """Best word-to-word alignment, and how much of each side it covers by weight."""

    pairs: list[tuple[float, int, int]] = []
    for i, q in enumerate(query):
        for j, n in enumerate(name):
            s = token_similarity(q, n, entity)
            if s:
                pairs.append((s, i, j))
    pairs.sort(reverse=True)
    used_q: set[int] = set()
    used_n: set[int] = set()
    chosen: list[tuple[str, str, float]] = []
    positions: list[tuple[int, int, float]] = []
    covered_q = covered_n = anchor = exact_anchor = 0.0
    best_distinctive = 0.0
    for s, i, j in pairs:
        if i in used_q or j in used_n:
            continue
        used_q.add(i)
        used_n.add(j)
        chosen.append((query[i], name[j], s))
        positions.append((i, j, s))
        if query_weights[i] > 0.2:
            # A long word with one slip is still telling; a short one must be exact.
            needed = 1.0 if len(query[i].replace(JOIN, "")) <= 7 else 0.85
            best_distinctive = max(best_distinctive, 1.0 if s >= needed else s)
        covered_q += s * query_weights[i]
        covered_n += s * name_weights[j]
        agrees = s >= 0.9 or (s >= 0.85 and len(query[i]) >= 7)  # a long word, one slip
        if agrees:
            anchor = max(anchor, min(query_weights[i], name_weights[j]))
            if s == 1.0:
                exact_anchor = max(exact_anchor, min(query_weights[i], name_weights[j]))
    total_q, total_n = sum(query_weights) or 1.0, sum(name_weights) or 1.0
    cq, cn = covered_q / total_q, covered_n / total_n
    # The party's name must be covered; a listed name's extra parts count for less,
    # and for a person less still: listings carry middle names and second surnames
    # that files leave out (RAFAEL QUINTERO for Rafael Antonio FRANCO QUINTERO).
    name_part = 0.3 if entity else 0.2
    score = (cq ** (1 - name_part)) * (cn**name_part) if cq and cn else 0.0
    all_exact = all(s == 1.0 for _, _, s in positions)
    any_exact = any(s == 1.0 and JOIN not in query[i] for i, _, s in positions)
    ordered = [j for _, j, _ in sorted(positions)]
    reversed_order = len(ordered) >= 2 and ordered != sorted(ordered)
    inexact = any(s < 1.0 for _, _, s in positions)
    return _Alignment(
        score=score,
        query_cover=cq,
        name_cover=cn,
        pairs=chosen,
        anchor=anchor,
        crosswise_inexact=reversed_order and inexact,
        crosswise=reversed_order,
        all_exact=all_exact,
        any_exact=any_exact,
        # Words matched only crosswise and inexactly: only exact ones show identity.
        anchor_if_crosswise=exact_anchor,
        distinctive_query_words=sum(1 for w in query_weights if w > 0.2),
        best_distinctive=best_distinctive,
    )


def _best_alignment(query: list[str], name: list[str], entity: bool) -> _Alignment:
    best = _Alignment(0.0, 0.0, 0.0)
    query_weights = [frequency.weight(t, entity=entity) for t in query]
    name_weights = [frequency.weight(t, entity=entity) for t in name]
    for q, qw in _joined(query, query_weights, entity):
        for n, nw in _joined(name, name_weights, entity):
            found = align(q, qw, n, nw, entity)
            if found.score > best.score:
                best = found
    return best


_YEAR = re.compile(r"\b(1[89]\d\d|20\d\d)\b")


def _years(values: list[str]) -> set[int]:
    found: set[int] = set()
    for v in values:
        ys = [int(y) for y in _YEAR.findall(v)]
        if len(ys) == 2 and " to " in v.lower():  # "1945 to 1950"
            found.update(range(ys[0], ys[1] + 1))
        else:
            found.update(ys)
    return found


class Screener:
    """An index over a set of list entries; screen as many parties as needed against it."""

    def __init__(self, entries: list[SanctionsEntry], thresholds: Thresholds | None = None) -> None:
        self.entries = entries
        self.thresholds = thresholds or Thresholds()
        self.forms: list[_Form] = []
        self._by_token: dict[str, set[int]] = defaultdict(set)
        self._by_key: dict[str, set[int]] = defaultdict(set)
        self._by_trigram: dict[str, set[int]] = defaultdict(set)
        self._by_letters: dict[str, set[int]] = defaultdict(set)
        for e_i, entry in enumerate(entries):
            entity = _is_entity(entry.entry_type)
            for n_i, listed in enumerate(entry.names):
                words = tokens(listed.full_name, entity=entity)
                if not words:
                    continue
                f_i = len(self.forms)
                self.forms.append(
                    _Form(
                        entry=e_i,
                        name=n_i,
                        tokens=words,
                        weights=[frequency.weight(t, entity=entity) for t in words],
                        keys=[phonetic.key(t) for t in words],
                    )
                )
                for t, k in zip(words, self.forms[-1].keys, strict=True):
                    self._by_token[t].add(f_i)
                    bare = unprefixed(t)
                    if bare:
                        self._by_token[bare].add(f_i)
                    if len(t) >= 5:
                        self._by_letters[phonetic.letters(t)].add(f_i)
                    if len(k) >= 2:
                        self._by_key[k].add(f_i)
                    if len(t) >= 4:
                        for g in phonetic.trigrams(t):
                            self._by_trigram[g].add(f_i)

    def _candidates(self, words: list[str]) -> set[int]:
        found: set[int] = set()
        for t in words:
            if len(t) == 1:
                continue
            found |= self._by_token.get(t, set())
            bare = unprefixed(t)
            if bare:
                found |= self._by_token.get(bare, set())
            if len(t) >= 5:
                found |= self._by_letters.get(phonetic.letters(t), set())
            k = phonetic.key(t)
            if len(k) >= 2:
                found |= self._by_key.get(k, set())
            if len(t) >= 4:
                grams = phonetic.trigrams(t)
                counts: dict[int, int] = defaultdict(int)
                for g in grams:
                    for f_i in self._by_trigram.get(g, ()):
                        counts[f_i] += 1
                need = max(3, math.ceil(len(grams) * 0.6))
                found |= {f_i for f_i, c in counts.items() if c >= need}
        for whole in ("".join(words),):  # a party name written as one word
            found |= self._by_token.get(whole, set())
        return found

    def screen(self, party: ScreeningParty) -> PartyScreening:
        entity_party = party.party_type is PartyType.ENTITY or (
            party.party_type is PartyType.UNKNOWN and _looks_like_entity(party.name)
        )
        words = tokens(party.name, entity=entity_party)
        best: dict[int, Candidate] = {}
        for f_i in self._candidates(words):
            form = self.forms[f_i]
            entry = self.entries[form.entry]
            candidate = self._score(party, words, entity_party, entry, form)
            if candidate is None:
                continue
            if form.entry not in best or candidate.score > best[form.entry].score:
                best[form.entry] = candidate
        ranked = sorted(best.values(), key=lambda c: -c.score)[: self.thresholds.max_candidates]
        outcome = (
            Outcome.POTENTIAL_MATCH
            if any(c.outcome is Outcome.POTENTIAL_MATCH for c in ranked)
            else Outcome.LIKELY_FALSE_POSITIVE
            if ranked
            else Outcome.NO_MATCH
        )
        return PartyScreening(party=party, outcome=outcome, candidates=ranked)

    def _score(
        self,
        party: ScreeningParty,
        words: list[str],
        entity_party: bool,
        entry: SanctionsEntry,
        form: _Form,
    ) -> Candidate | None:
        reasons: list[str] = []
        listed_entity = _is_entity(entry.entry_type)
        # A person is never a vessel, aircraft or company; a company is never a vessel.
        if party.party_type is PartyType.INDIVIDUAL and listed_entity:
            return None
        if entity_party and entry.entry_type in (EntryType.VESSEL, EntryType.AIRCRAFT):
            return None
        person_like = party.party_type is PartyType.UNKNOWN and not entity_party
        if person_like and entry.entry_type in (EntryType.VESSEL, EntryType.AIRCRAFT):
            return None
        aligned = _best_alignment(words, form.tokens, entity=entity_party or listed_entity)
        score = aligned.score
        if not score:
            return None
        listed = entry.names[form.name]
        reasons.append(
            f"{len(aligned.pairs)} of {len(words)} words matched "
            f"(covers {aligned.query_cover:.0%} of the party's name by weight, "
            f"{aligned.name_cover:.0%} of the listed name)"
        )
        if aligned.crosswise_inexact:
            score *= 0.93
            reasons.append("Words agree only in a different order, and not all exactly.")
        elif aligned.crosswise and (entity_party or listed_entity):
            score *= 0.9  # people are written LAST, FIRST; company names are not reordered
            reasons.append("The company's words agree only in a different order.")
        if entity_party and entry.entry_type is EntryType.INDIVIDUAL:
            score *= 0.85
            reasons.append("Party is a company; the listing is an individual.")
        if person_like and listed_entity:
            score *= 0.85
            reasons.append("Party looks like a person; the listing is an organization.")
        party_years = _years([party.date_of_birth]) if party.date_of_birth else set()
        listed_years = _years(entry.dates_of_birth)
        corroborated = False
        if party_years and listed_years:
            if any(abs(a - b) <= 1 for a in party_years for b in listed_years):
                score = min(1.0, score + 0.05)
                corroborated = True
                reasons.append("Date of birth agrees with the listing.")
            elif all(abs(a - b) > 2 for a in party_years for b in listed_years):
                score *= 0.75
                reasons.append(
                    f"Date of birth differs from the listing ({', '.join(entry.dates_of_birth)})."
                )
        t = self.thresholds
        outcome = (
            Outcome.POTENTIAL_MATCH
            if score >= t.potential_match
            else Outcome.LIKELY_FALSE_POSITIVE
            if score >= t.likely_false_positive
            else None
        )
        if outcome is None:
            return None
        if (
            outcome is Outcome.POTENTIAL_MATCH
            and listed.quality is AliasQuality.WEAK
            and not corroborated
        ):
            outcome = Outcome.LIKELY_FALSE_POSITIVE
            reasons.append("Matched only a weak alias, which OFAC says is not a match by itself.")
        anchor = aligned.anchor_if_crosswise if aligned.crosswise_inexact else aligned.anchor
        if outcome is Outcome.POTENTIAL_MATCH and not listed_entity and not aligned.any_exact:
            outcome = Outcome.LIKELY_FALSE_POSITIVE
            reasons.append("No word of the name matches exactly.")
        partial = aligned.name_cover < t.partial_name_cover and not listed_entity
        if outcome is Outcome.POTENTIAL_MATCH and (partial or aligned.crosswise_inexact):
            if not aligned.all_exact or anchor < t.partial_anchor_weight:
                outcome = Outcome.LIKELY_FALSE_POSITIVE
                reasons.append(
                    "Matches only part of the listed name"
                    if partial
                    else "Matches only crosswise and inexactly"
                )
                reasons[-1] += ", and not exactly on a rare word."
        if outcome is Outcome.POTENTIAL_MATCH and score < 0.97 and anchor < t.anchor_weight:
            outcome = Outcome.LIKELY_FALSE_POSITIVE
            reasons.append("Matched only on common names; no distinctive word agrees.")
        # The listed name entire, word for word: an exact match always alerts.
        whole_name = aligned.all_exact and aligned.name_cover >= 0.97
        if outcome is Outcome.POTENTIAL_MATCH and entity_party and not whole_name:
            if aligned.distinctive_query_words == 0:
                outcome = Outcome.LIKELY_FALSE_POSITIVE
                reasons.append("The party's name is made only of common business words.")
            elif aligned.distinctive_query_words == 1 and (
                aligned.best_distinctive < 1.0 or aligned.name_cover < 0.85
            ):
                outcome = Outcome.LIKELY_FALSE_POSITIVE
                reasons.append(
                    "The party's name has one distinctive word, and it does not match the "
                    "listed name closely and completely."
                )
        if entry.address_countries and "United States" not in entry.address_countries:
            reasons.append(
                "Listed addresses are outside the United States "
                f"({', '.join(entry.address_countries[:4])}); informational only."
            )
        return Candidate(
            uid=entry.uid,
            sanctions_list=entry.sanctions_list,
            entry_type=entry.entry_type,
            listed_name=entry.primary_name,
            matched_name=listed.full_name,
            matched_name_quality=listed.quality,
            score=round(min(score, 1.0), 3),
            outcome=outcome,
            matched_tokens=[
                (f"{q}={n}" if q != n else q).replace(JOIN, "") for q, n, _ in aligned.pairs
            ],
            reasons=reasons,
            programs=entry.programs,
            dates_of_birth=entry.dates_of_birth,
            nationalities=entry.nationalities,
            address_countries=entry.address_countries,
        )
