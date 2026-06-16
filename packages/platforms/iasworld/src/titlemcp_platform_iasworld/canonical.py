from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from title_mcp.domain.auditor import (
    MoneyAmount,
    PropertyAssessmentAnnualTax,
    PropertyAssessmentDwelling,
    PropertyAssessmentOwnership,
    PropertyAssessmentParcel,
    PropertyAssessmentProperty,
    PropertyAssessmentRecord,
    PropertyAssessmentSearchContext,
    PropertyAssessmentSite,
    PropertyAssessmentSource,
    PropertyAssessmentTaxStatus,
    PropertyAssessmentTaxSummary,
    PropertyAssessmentTransfer,
    PropertyAssessmentValuation,
    PropertyAssessmentValueLine,
    PropertyAssessmentValueTable,
)
from title_mcp.domain.models import Address, Jurisdiction
from titlemcp_platform_iasworld.models import (
    IasWorldAuditorParcelDetail,
    IasWorldAuditorSearchHit,
    IasWorldAuditorSearchResponse,
)


def canonical_property_assessments_from_iasworld_response(
    response: IasWorldAuditorSearchResponse,
    *,
    source_id: str,
    source_name: str,
    jurisdiction: Jurisdiction,
) -> list[PropertyAssessmentRecord]:
    detail_by_parcel = {
        detail.parcel_number: detail for detail in response.details if detail.parcel_number
    }
    records: list[PropertyAssessmentRecord] = []
    used_detail_parcels: set[str] = set()

    for index, hit in enumerate(response.results):
        detail = detail_by_parcel.get(hit.parcel_number or "")
        if detail and detail.parcel_number:
            used_detail_parcels.add(detail.parcel_number)
        records.append(
            _record_from_hit_and_detail(
                response=response,
                hit=hit,
                detail=detail,
                result_index=index,
                source_id=source_id,
                source_name=source_name,
                jurisdiction=jurisdiction,
            )
        )

    for detail in response.details:
        if detail.parcel_number and detail.parcel_number in used_detail_parcels:
            continue
        records.append(
            _record_from_hit_and_detail(
                response=response,
                hit=None,
                detail=detail,
                result_index=None,
                source_id=source_id,
                source_name=source_name,
                jurisdiction=jurisdiction,
            )
        )

    return records


def _record_from_hit_and_detail(
    *,
    response: IasWorldAuditorSearchResponse,
    hit: IasWorldAuditorSearchHit | None,
    detail: IasWorldAuditorParcelDetail | None,
    result_index: int | None,
    source_id: str,
    source_name: str,
    jurisdiction: Jurisdiction,
) -> PropertyAssessmentRecord:
    tax_status = detail.tax_status if detail else {}
    tax_year = _tax_year_from_detail(detail)
    parcel_number = _first(
        detail.parcel_number if detail else None,
        hit.parcel_number if hit else None,
    )
    parcel_id = _first(detail.parcel_id if detail else None, hit.parcel_id if hit else None)
    parcel_token = _first(
        detail.parcel_token if detail else None,
        hit.parcel_token if hit else None,
    )
    site_address_lines = _clean_lines(
        [
            detail.site_property_address if detail else None,
            detail.site_address if detail else None,
            hit.address if hit else None,
        ],
        remove_correction_requests=True,
        first_only=True,
    )
    mailing_address_lines = _clean_lines(
        detail.owner_mailing_address if detail else [],
        remove_correction_requests=True,
    )

    source = PropertyAssessmentSource(
        source_id=source_id,
        source_name=source_name,
        source_url=detail.source_url if detail else hit.detail_url if hit else None,
        search_url=response.search_url,
        detail_url=detail.source_url if detail else hit.detail_url if hit else None,
        retrieved_at=detail.retrieved_at if detail else response.retrieved_at,
    )
    parcel = PropertyAssessmentParcel(
        parcel_id=parcel_id,
        parcel_number=parcel_number,
        normalized_parcel_id=parcel_number,
        parcel_token=parcel_token,
        tax_authority_parcel_token=parcel_token,
        tax_authority_jurisdiction=_first(
            detail.jurisdiction if detail else None,
            hit.jurisdiction if hit else None,
        ),
        tax_year=_first(detail.tax_year if detail else None, hit.tax_year if hit else None),
        map_routing=detail.map_routing if detail else None,
        permalink=detail.permalink if detail else None,
    )
    owner_names = detail.owners if detail and detail.owners else _clean_lines(
        [hit.owner if hit else None]
    )
    ownership = PropertyAssessmentOwnership(
        owner_display=_first(detail.owner_display if detail else None, hit.owner if hit else None),
        owners=owner_names,
        mailing_address=_address_from_lines(mailing_address_lines),
        mailing_address_lines=mailing_address_lines,
        raw=_raw_owner(detail),
    )
    property_profile = PropertyAssessmentProperty(
        site_address_display=site_address_lines[0] if site_address_lines else None,
        site_address=_address_from_lines(
            site_address_lines,
            postal_code=_string_or_none(tax_status.get("Zip Code")),
            state=jurisdiction.state,
        ),
        site_address_lines=site_address_lines,
        legal_description_lines=detail.legal_description if detail else [],
        legal_description_text=(
            " ".join(detail.legal_description) if detail and detail.legal_description else None
        ),
        legal_acres=_decimal_or_none(detail.legal_acres if detail else None),
        property_class=_string_or_none(tax_status.get("Property Class")),
        land_use=_string_or_none(tax_status.get("Land Use")),
        tax_district=_string_or_none(tax_status.get("Tax District")),
        school_district=_string_or_none(tax_status.get("School District")),
        municipality=_string_or_none(tax_status.get("City/Village")),
        township=_string_or_none(tax_status.get("Township")),
        appraisal_neighborhood=_string_or_none(tax_status.get("Appraisal Neighborhood")),
        postal_code=_string_or_none(tax_status.get("Zip Code")),
        raw={"tax_status": tax_status},
    )
    return PropertyAssessmentRecord(
        source=source,
        jurisdiction=jurisdiction,
        search=PropertyAssessmentSearchContext(
            mode=response.search_mode.value,
            query=response.query.model_dump(mode="json"),
            result_count=response.result_count,
            result_index=result_index,
            result_hit=hit.model_dump(mode="json") if hit else None,
        ),
        parcel=parcel,
        ownership=ownership,
        property=property_profile,
        transfer=_transfer(detail),
        tax_status=_tax_status(detail, tax_year),
        valuation=PropertyAssessmentValuation(
            appraised=_value_table(
                detail.appraised_value if detail else {},
                value_type="appraised",
                tax_year=tax_year,
            ),
            taxable=_value_table(
                detail.taxable_value if detail else {},
                value_type="taxable",
                tax_year=tax_year,
            ),
        ),
        taxes=_taxes(detail),
        dwelling=_dwelling(detail),
        site=_site(detail),
        source_specific={
            "iasworld_auditor": {
                "hit": hit.model_dump(mode="json") if hit else None,
                "detail": detail.model_dump(mode="json") if detail else None,
            }
        },
    )


def _raw_owner(detail: IasWorldAuditorParcelDetail | None) -> dict[str, Any]:
    if not detail:
        return {}
    owner_section = detail.sections.get("Owner")
    return owner_section if isinstance(owner_section, dict) else {}


def _transfer(detail: IasWorldAuditorParcelDetail | None) -> PropertyAssessmentTransfer | None:
    if not detail or not detail.most_recent_transfer:
        return None
    raw = detail.most_recent_transfer
    return PropertyAssessmentTransfer(
        transfer_date=_string_or_none(raw.get("Transfer Date")),
        transfer_price=_money_or_none(raw.get("Transfer Price")),
        instrument_type=_string_or_none(raw.get("Instrument Type")),
        parcel_count=_int_or_none(raw.get("Parcel Count")),
        raw=raw,
    )


def _tax_status(
    detail: IasWorldAuditorParcelDetail | None,
    tax_year: str | None,
) -> PropertyAssessmentTaxStatus:
    raw = detail.tax_status if detail else {}
    return PropertyAssessmentTaxStatus(
        tax_year=tax_year,
        property_class=_string_or_none(raw.get("Property Class")),
        land_use=_string_or_none(raw.get("Land Use")),
        tax_district=_string_or_none(raw.get("Tax District")),
        school_district=_string_or_none(raw.get("School District")),
        municipality=_string_or_none(raw.get("City/Village")),
        township=_string_or_none(raw.get("Township")),
        appraisal_neighborhood=_string_or_none(raw.get("Appraisal Neighborhood")),
        postal_code=_string_or_none(raw.get("Zip Code")),
        tax_lien=_yes_no_or_none(raw.get("Tax Lien")),
        cdq=_yes_no_or_none(raw.get("CDQ")),
        cauv_property=_yes_no_or_none(raw.get("CAUV Property")),
        owner_occupancy_credit=_year_bool_map(raw.get("Owner Occ. Credit")),
        homestead_credit=_year_bool_map(raw.get("Homestead Credit")),
        rental_registration=_yes_no_or_none(raw.get("Rental Registration")),
        rental_exception=_yes_no_or_none(raw.get("Rental Exception")),
        board_of_revision=_yes_no_or_none(raw.get("Board of Revision")),
        pending_exemption=_yes_no_or_none(raw.get("Pending Exemption")),
        raw=raw,
    )


def _value_table(
    table: dict[str, Any],
    *,
    value_type: str,
    tax_year: str | None,
) -> PropertyAssessmentValueTable | None:
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return None

    value_rows: list[PropertyAssessmentValueLine] = []
    summary: dict[str, PropertyAssessmentValueLine] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        category = _string_or_none(row.get("")) or _string_or_none(row.get("Category"))
        if not category:
            continue
        line = PropertyAssessmentValueLine(
            category=category,
            land=_money_or_none(row.get("Land")),
            improvements=_money_or_none(row.get("Improvements")),
            total=_money_or_none(row.get("Total")),
            raw=row,
        )
        value_rows.append(line)
        summary[_key(category)] = line

    return PropertyAssessmentValueTable(
        value_type=value_type,  # type: ignore[arg-type]
        tax_year=tax_year,
        rows=value_rows,
        summary=summary,
        raw=table,
    )


def _taxes(detail: IasWorldAuditorParcelDetail | None) -> PropertyAssessmentTaxSummary:
    table = detail.annual_taxes if detail else {}
    rows = table.get("rows") if isinstance(table, dict) else None
    taxes: list[PropertyAssessmentAnnualTax] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            taxes.append(
                PropertyAssessmentAnnualTax(
                    tax_year=_string_or_none(row.get("Tax Year")),
                    net_annual_tax=_money_or_none(row.get("Net Annual Tax")),
                    total_paid=_money_or_none(row.get("Total Paid")),
                    raw=row,
                )
            )
    return PropertyAssessmentTaxSummary(annual=taxes, raw=table if isinstance(table, dict) else {})


def _dwelling(detail: IasWorldAuditorParcelDetail | None) -> PropertyAssessmentDwelling | None:
    first = _first_table_row(detail.dwelling_data if detail else {})
    if not first:
        return None
    return PropertyAssessmentDwelling(
        year_built=_int_or_none(first.get("Yr Built")),
        total_finished_area_sqft=_int_or_none(first.get("Tot Fin Area")),
        rooms=_int_or_none(first.get("Rooms")),
        bedrooms=_int_or_none(first.get("Bedrooms")),
        full_baths=_int_or_none(first.get("Full Baths")),
        half_baths=_int_or_none(first.get("Half Baths")),
        raw=first,
    )


def _site(detail: IasWorldAuditorParcelDetail | None) -> PropertyAssessmentSite | None:
    first = _first_table_row(detail.site_data if detail else {})
    if not first:
        return None
    return PropertyAssessmentSite(
        frontage_feet=_decimal_or_none(first.get("Frontage")),
        depth_feet=_decimal_or_none(first.get("Depth")),
        acres=_decimal_or_none(first.get("Acres")),
        raw=first,
    )


def _first_table_row(table: dict[str, Any]) -> dict[str, Any] | None:
    rows = table.get("rows") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return None
    return next((row for row in rows if isinstance(row, dict)), None)


def _tax_year_from_detail(detail: IasWorldAuditorParcelDetail | None) -> str | None:
    if not detail:
        return None
    annual_tax = _first_table_row(detail.annual_taxes)
    annual_tax_year = _string_or_none(annual_tax.get("Tax Year")) if annual_tax else None
    return annual_tax_year or detail.tax_year


def _money_or_none(value: Any) -> MoneyAmount | None:
    text = _string_or_none(value)
    if text is None:
        return None
    return MoneyAmount(display=text, value=_decimal_or_none(text))


def _decimal_or_none(value: Any) -> Decimal | None:
    text = _string_or_none(value)
    if text is None:
        return None
    normalized = re.sub(r"[^0-9.\-]", "", text)
    if normalized in {"", ".", "-", "-."}:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _int_or_none(value: Any) -> int | None:
    decimal_value = _decimal_or_none(value)
    return int(decimal_value) if decimal_value is not None else None


def _yes_no_or_none(value: Any) -> bool | None:
    text = _string_or_none(value)
    if text is None:
        return None
    normalized = text.lower()
    if normalized == "yes":
        return True
    if normalized == "no":
        return False
    return None


def _year_bool_map(value: Any) -> dict[str, bool]:
    text = _string_or_none(value)
    if text is None:
        return {}
    result: dict[str, bool] = {}
    for year, flag in re.findall(r"(\d{4})\s*:\s*(Yes|No)", text, flags=re.IGNORECASE):
        result[year] = flag.lower() == "yes"
    return result


def _address_from_lines(
    lines: list[str],
    *,
    postal_code: str | None = None,
    state: str | None = None,
) -> Address | None:
    if not lines:
        return None
    address = Address(line1=lines[0])
    if len(lines) > 1:
        city_line = lines[1]
        match = re.match(r"^(.+?)\s+([A-Z]{2})\s+(\d{5}(?:[-\s]\d{4})?)$", city_line)
        if match:
            address.city = match.group(1)
            address.state = match.group(2)
            address.postal_code = match.group(3)
        else:
            address.line2 = city_line
    elif postal_code:
        address.state = state
        address.postal_code = postal_code
    return address


def _clean_lines(
    values: Any,
    *,
    remove_correction_requests: bool = False,
    first_only: bool = False,
) -> list[str]:
    if values is None:
        return []
    candidates = values if isinstance(values, list) else [values]
    lines: list[str] = []
    for value in candidates:
        text = _string_or_none(value)
        if not text:
            continue
        if remove_correction_requests and "Correction Request" in text:
            continue
        if text not in lines:
            lines.append(text)
        if first_only and lines:
            break
    return lines


def _first(*values: str | None) -> str | None:
    return next((value for value in values if value), None)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return " ".join(values) or None
    text = str(value).strip()
    return text or None


def _key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return key or "unknown"
