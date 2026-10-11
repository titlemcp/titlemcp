# titlemcp-us-dc-tax

District of Columbia real property tax status for TitleMCP. The connector
(`us-dc-otr-tax`, kind `tax_authority`) answers `property_tax_status_search`
for any parcel in the District.

## Source

The Office of Tax and Revenue publishes its **Integrated Tax System Public
Extract** on [Open Data DC](https://opendata.dc.gov/datasets/DCGIS::integrated-tax-system-public-extract):
- it's refreshed every weekday;
- it's licensed under Creative Commons Attribution 4.0;
- it needs no credential.

For each parcel (SSL), the extract has:
- the current year's two halves: tax, penalty, interest, fees, collected and balance;
- ten prior years, with tax sale flags;
- special assessments: business improvement district, PACE, SEWS and SWWSAD.

The extract is an ArcGIS feature layer. The District republishes it under new
service names, so the connector finds the layer through its ArcGIS Online item.
It reads the layer's last-edit date, and each answer carries that date as
`source.data_as_of`.

## Parcels

A parcel is its square, suffix and lot. The extract pads each to four
characters, so square 4559, lot 63 is stored as `4559    0063`. The connector
accepts the usual written forms:
- `4559 0063`
- `4559-63`
- `Square 4559 Lot 63`
- `5245N 0035`

Other parcel kinds (`PAR …`, `PI…`) are matched as written.

## Status

The first half is due March 31 and the second half September 15
(D.C. Code § 47-811(b)), so a balance on a half after its date is `past_due`.
A balance on a prior year is too. A bill mailed late is due later than the
statutory date. Confirm a balance owed, or a payment made since the extract's
date, on MyTax.DC.gov before closing.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/dc/tax
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/dc/tax/tests -v
```
