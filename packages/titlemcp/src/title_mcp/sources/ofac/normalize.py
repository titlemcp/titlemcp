"""Turning a name into comparable tokens: folding, transliteration, particles, suffixes."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

#: Honorifics and titles that say nothing about identity.
TITLES = frozenset(
    "MR MRS MS MISS DR PROF SIR SHEIKH SHAIKH SHEIK HAJI HAJJI HAJ MULLAH MAULANA REV "
    "GEN COL MAJ CAPT LT SGT JR SR II III IV ESQ".split()
)

#: Name particles: kept, but they weigh little (AL, BIN, VAN, DE ...).
PARTICLES = frozenset(
    "AL EL UL BIN IBN BEN BINT BENT ABU UMM ABD ABDEL ABDUL VAN VON DER DEN DE DA DO DOS DAS "
    "DEL DELLA DI DU LA LE LOS LAS Y E".split()
)

#: Legal-form suffixes on organisations, removed before matching.
ENTITY_SUFFIXES = frozenset(
    "LLC LLP LP LTD LIMITED INC INCORPORATED CORP CORPORATION CO COMPANY PLC PC PLLC SA SAS SRL "
    "SPA GMBH AG KG BV NV OOO OAO ZAO PAO PJSC JSC CJSC OJSC PTE PTY BHD SDN FZE FZCO FZC FZ "
    "LLC-FZ AB AS OY SE SARL SL SAC SACV CV DE RL TRUST".split()
)

#: Words so common in company names that they say little on their own.
GENERIC_ENTITY_WORDS = frozenset(
    "GLOBAL INTERNATIONAL INTL TRADING TRADE HOLDING HOLDINGS GROUP ENTERPRISE ENTERPRISES "
    "SERVICE SERVICES INVESTMENT INVESTMENTS CAPITAL INDUSTRIES INDUSTRY INDUSTRIAL COMMERCIAL "
    "GENERAL NATIONAL UNITED AMERICAN FIRST NEW PROPERTIES PROPERTY REALTY REAL ESTATE "
    "MANAGEMENT DEVELOPMENT CONSTRUCTION ASSOCIATES PARTNERS PARTNERSHIP FUND FUNDS "
    "SOLUTIONS SYSTEMS TECHNOLOGIES TECHNOLOGY TECH GROUP CENTER CENTRE OF THE AND FOR "
    "IMPORT EXPORT SHIPPING LOGISTICS ENERGY OIL GAS PETROLEUM BANK FINANCIAL FINANCE "
    "HOMES HOME LAND TITLE MARINE TRANSPORT CONSULTING MEDIA FOODS AGENCY SALES MARKETING "
    "LENDING LENDERS LOAN LOANS MORTGAGE CREDIT UNION SAVINGS FEDERAL COMMUNITY STATE COUNTY "
    "CITY EQUITY RENTALS RENTAL VENTURES ACQUISITIONS INVESTORS BUILDERS REALTORS BROKERS "
    "BROKERAGE ADVISORS INSURANCE MOTORS AUTO FARMS FARM RANCH SUPPLY STORE RESTAURANT CHURCH "
    "MINISTRIES ASSOCIATION SOCIETY FOUNDATION OWNERS ESTATES PLAZA VILLAGE PARK "
    "CONTRACTING CONTRACTORS CONTRACTOR LEASING ROOFING PLUMBING ELECTRIC ELECTRICAL "
    "HEATING COOLING LANDSCAPING CLEANING PAINTING REMODELING RESTORATION EXCAVATING PAVING "
    "CONCRETE MASONRY HAULING TRUCKING TRANSPORTATION MOVING STORAGE FLOORING CUSTOM QUALITY "
    "PREMIER ELITE PRO SUPERIOR ADVANCED ALLIANCE SONS BROTHERS FAMILY".split()
)

#: Given names so common worldwide, and on sanctions lists, that matching one says
#: little, however rare the U.S. Census finds them.
COMMON_GLOBAL_GIVEN_NAMES = frozenset(
    "MUHAMMAD AHMAD ALI HASAN HUSAYN ABDULLAH MAHMUD MUSTAFA UMAR UTHMAN KHALID SAID YUSUF "
    "IBRAHIM ISMAIL ABDUL HAMID JAMAL KARIM RAHMAN SALEH SALIH NASSER NASIR ABBAS HAMZA "
    "ADEL ADIL TARIQ WALID FAISAL SULAIMAN SULEIMAN".split()
)

#: Joining words in organisation names: never identifying, so never matched.
ENTITY_STOP_WORDS = frozenset("AND OF THE FOR A AN DE DU LA LE LES Y ET".split())

#: Spellings of the same transliterated name, mapped to one form. The phonetic key
#: catches many more; these are the ones it cannot.
VARIANTS = {
    **dict.fromkeys(
        "MOHAMMED MOHAMMAD MOHAMED MOHAMAD MUHAMMED MUHAMAD MUHAMMET MEHMET MOHAMMEED "
        "MOHAMMADD MUHAMMADU MOHD MOHAMMOD MOHAMMOUD".split(),
        "MUHAMMAD",
    ),
    **dict.fromkeys("AHMED AHMET AHAMED AHMAED".split(), "AHMAD"),
    **dict.fromkeys(
        "HUSSEIN HUSSAIN HOSSEIN HUSEIN HUSAIN HOSEIN HUSAYN HUSSEINI".split(), "HUSAYN"
    ),
    **dict.fromkeys("HASSAN HASAN HASSANE".split(), "HASAN"),
    **dict.fromkeys("YOUSSEF YOUSEF YUSSUF YOUSUF YUSUPH YOSEF JOUSSEF JUSUF".split(), "YUSUF"),
    **dict.fromkeys("OSAMA USAMA OUSSAMA".split(), "USAMA"),
    **dict.fromkeys("ABDULLAH ABDALLAH ABDULLA ABDALLA ABDOULAYE".split(), "ABDULLAH"),
    **dict.fromkeys("MAHMOUD MAHMUD MAHMOOD".split(), "MAHMUD"),
    **dict.fromkeys("MUSTAFA MOSTAFA MOUSTAFA MUSTAPHA".split(), "MUSTAFA"),
    **dict.fromkeys("OMAR UMAR OMER".split(), "UMAR"),
    **dict.fromkeys("OTHMAN USMAN OSMAN UTHMAN OTMAN".split(), "UTHMAN"),
    **dict.fromkeys("KHALED KHALID CHALED".split(), "KHALID"),
    **dict.fromkeys("SAEED SAID SAYED SAYYID SAYYED SEYED SEYYED".split(), "SAID"),
    **dict.fromkeys("ALEKSANDR ALEXANDR ALEXANDER OLEKSANDR ALEKSANDER".split(), "ALEKSANDR"),
    **dict.fromkeys("SERGEI SERGEY SERHIY SERGIY".split(), "SERGEI"),
    **dict.fromkeys("YURI YURIY IURII JURIJ".split(), "YURI"),
    **dict.fromkeys("DMITRI DMITRY DMITRIY DMYTRO".split(), "DMITRI"),
    **dict.fromkeys("VLADIMIR VOLODYMYR WLADIMIR".split(), "VLADIMIR"),
    **dict.fromkeys("MIKHAIL MYKHAILO MICHAIL".split(), "MIKHAIL"),
    **dict.fromkeys("NIKOLAI NIKOLAY MYKOLA".split(), "NIKOLAI"),
    **dict.fromkeys("EVGENY YEVGENY YEVGENIY EVGENIY IEVGEN".split(), "EVGENY"),
}

_SPLIT = re.compile(r"[^A-Z0-9]+")
_VARIANT_KEYS = tuple(sorted(VARIANTS))
_SUFFIX_KEYS = tuple(sorted(s for s in ENTITY_SUFFIXES if len(s) >= 5))


def fold(text: str) -> str:
    """Upper-case ASCII: accents removed, punctuation turned into spaces."""

    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(_SPLIT.split(ascii_text.upper())).strip()


def canonical(token: str) -> str:
    """One spelling for transliteration variants, a mistyped one included (MOAHMED)."""

    return VARIANTS.get(token) or _near(token, VARIANTS) or token


@lru_cache(maxsize=65536)
def _near_key(token: str, keys: tuple[str, ...]) -> str | None:
    if len(token) < 5:
        return None
    for key in keys:
        if key[0] == token[0] and abs(len(key) - len(token)) <= 1 and _one_edit(token, key):
            return key
    return None


def _near(token: str, table: dict[str, str]) -> str | None:
    key = _near_key(token, _VARIANT_KEYS)
    return table[key] if key else None


def _one_edit(a: str, b: str) -> bool:
    """Whether a and b differ by one substitution, insertion, deletion or swap of neighbours."""

    if a == b:
        return False
    if len(a) == len(b):
        diffs = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diffs) == 1:
            return True
        return (
            len(diffs) == 2
            and diffs[1] == diffs[0] + 1
            and a[diffs[0]] == b[diffs[1]]
            and a[diffs[1]] == b[diffs[0]]
        )
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    return any(long_[:i] + long_[i + 1 :] == short for i in range(len(long_)))


def is_suffix(token: str) -> bool:
    """A legal-form word, or one mistyped by a single slip (LIMITDE, COMPNAY)."""

    return token in ENTITY_SUFFIXES or _near_key(token, _SUFFIX_KEYS) is not None


def unprefixed(token: str) -> str | None:
    """The word without an attached AL-/EL- (ALRASHID -> RASHID), when it may be one.

    Offered as an alternative, never applied: ALEKSEI is a name, not AL + EKSEI.
    """

    for prefix in ("AL", "EL"):
        rest = token[len(prefix) :]
        if token.startswith(prefix) and len(rest) >= 4:
            return VARIANTS.get(rest, rest)
    return None


def _join_letters(found: list[str]) -> list[str]:
    """Runs of single letters become one token: L L C -> LLC, U S A -> USA."""

    joined: list[str] = []
    run = ""
    for t in [*found, ""]:
        if len(t) == 1:
            run += t
            continue
        if run:
            joined.append(run)
            run = ""
        if t:
            joined.append(t)
    return joined


def tokens(name: str, *, entity: bool = False) -> list[str]:
    """The name's tokens in order: titles dropped, suffixes dropped for organisations."""

    if entity:  # a letter hyphenated to a word is part of it: Z-FINANCE -> ZFINANCE
        name = re.sub(r"\b([A-Za-z])-(?=[A-Za-z])", r"\1", name)
    found = [t for t in fold(name).split() if t and t not in TITLES]
    if entity:
        found = _join_letters(found)
        if len(found) >= 2 and len(found[0]) == 1:  # T BANK -> TBANK
            found = [found[0] + found[1], *found[2:]]
        while found and is_suffix(found[-1]):
            found.pop()
        found = [t for t in found if not is_suffix(t) or len(found) == 1]
        kept = [t for t in found if t not in ENTITY_STOP_WORDS and len(t) > 1]
        found = kept or found
    return [canonical(t) for t in found]
