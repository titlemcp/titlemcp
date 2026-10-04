"""Records for OFAC screening: list entries, parties to screen, candidates and results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SanctionsList(StrEnum):
    SDN = "sdn"
    CONSOLIDATED = "consolidated"


class EntryType(StrEnum):
    INDIVIDUAL = "individual"
    ENTITY = "entity"
    VESSEL = "vessel"
    AIRCRAFT = "aircraft"


class PartyType(StrEnum):
    INDIVIDUAL = "individual"
    ENTITY = "entity"
    UNKNOWN = "unknown"


class AliasQuality(StrEnum):
    PRIMARY = "primary"
    STRONG = "strong"
    #: OFAC's own flag: a weak a.k.a. should not by itself be treated as a match.
    WEAK = "weak"


class Outcome(StrEnum):
    POTENTIAL_MATCH = "potential_match"
    LIKELY_FALSE_POSITIVE = "likely_false_positive"
    NO_MATCH = "no_match"


class ListName(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str
    quality: AliasQuality = AliasQuality.PRIMARY
    alias_type: str = ""


class SanctionsEntry(BaseModel):
    """One listed person, entity, vessel or aircraft, with what identifies it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    uid: str
    sanctions_list: SanctionsList
    entry_type: EntryType
    names: list[ListName]
    programs: list[str] = Field(default_factory=list)
    dates_of_birth: list[str] = Field(default_factory=list)
    places_of_birth: list[str] = Field(default_factory=list)
    nationalities: list[str] = Field(default_factory=list)
    address_countries: list[str] = Field(default_factory=list)
    remarks: str = ""

    @property
    def primary_name(self) -> str:
        return self.names[0].full_name if self.names else ""


class ListVersion(BaseModel):
    """Which publication of a list a screening used: the evidence for the file."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sanctions_list: SanctionsList
    publish_date: str
    record_count: int
    sha256: str
    source_url: str
    retrieved_at: str


class ScreeningParty(BaseModel):
    """A name to screen, with whatever else the file knows about it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    party_type: PartyType = PartyType.UNKNOWN
    date_of_birth: str | None = None
    role: str | None = None
    reference: str | None = None

    @field_validator("name")
    @classmethod
    def name_required(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("A party needs a name to screen.")
        return value


class Candidate(BaseModel):
    """A list entry that resembles the party, and exactly why it scored as it did."""

    model_config = ConfigDict(str_strip_whitespace=True)

    uid: str
    sanctions_list: SanctionsList
    entry_type: EntryType
    listed_name: str
    matched_name: str
    matched_name_quality: AliasQuality
    score: float = Field(ge=0.0, le=1.0)
    outcome: Outcome
    matched_tokens: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    programs: list[str] = Field(default_factory=list)
    dates_of_birth: list[str] = Field(default_factory=list)
    nationalities: list[str] = Field(default_factory=list)
    address_countries: list[str] = Field(default_factory=list)


class PartyScreening(BaseModel):
    party: ScreeningParty
    outcome: Outcome
    candidates: list[Candidate] = Field(default_factory=list)


class OfacScreeningRecord(BaseModel):
    """The canonical result of screening one or more parties."""

    model_config = ConfigDict(str_strip_whitespace=True)

    schema_name: str = "title_mcp.ofac_screening"
    schema_version: str = "1"
    record_type: str = "ofac_screening"
    screened_at: str
    #: Where the record came from, as other canonical records carry it.
    source: dict[str, Any] = Field(default_factory=dict)
    lists: list[ListVersion]
    thresholds: dict[str, float]
    outcome: Outcome
    parties: list[PartyScreening]
    requires_human_review: bool = True
    method: str = (
        "Names and aliases from OFAC's lists, matched on several keys (spelling, sound, "
        "transliteration); each word weighted by how common it is in the United States; "
        "OFAC's weak aliases cannot match by themselves; entity type and date of birth "
        "corroborate or discount. No candidate is cleared automatically."
    )
    source_specific: dict[str, Any] = Field(default_factory=dict)
