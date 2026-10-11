# titlemcp-us-ca-tax

California county property tax status for TitleMCP. The connector
`us-ca-contra-costa-tax` (kind `tax_authority`) answers
`property_tax_status_search` for secured parcels in Contra Costa County.

## Source

The Contra Costa County Treasurer-Tax Collector's
[Tax Lookup](https://taxcolp.cccttc.us/lookup/) answers from a JSON endpoint,
the one its own page calls. It needs no credential. For a parcel it lists:
- each installment of the current and prior years: amount, the last day to pay
  before it is delinquent, paid date and status;
- supplemental bills and redemption (defaulted tax) bills, the same way;
- flags for delinquency, prior years owed and payment plans;
- the date the amounts are good for, which the answer carries as
  `source.data_as_of`.

The county's page notes that pending payments or corrections may not show yet.

## Parcels

A parcel is its APN, ten digits with a check digit last: `123-456-789-1`. The
connector accepts it with or without dashes or spaces, and without the check
digit, as the county's lookup does.

## Status

The county's lookup shows the first installment due November 1 and the second
February 1. Each installment's date here is the last day to pay it before it is
delinquent, as the county gives it; weekends and holidays move it. So:
- an installment owed after its date is `past_due`;
- a redemption bill is a delinquent earlier year, so it is `past_due` too;
- a supplemental bill that isn't delinquent is listed as an other charge, with
  its installments' dates in the notes. A delinquent one joins its tax year.

A pending payment is counted as owed until it clears. An installment the
connector doesn't read leaves the whole answer `unknown`, never `paid`: a
partial payment, a bill type other than secured, supplemental or redemption, or
a delinquency flag with no delinquent installment listed.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/ca/tax
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/ca/tax/tests -v
```

The fixtures are invented and shaped like the lookup's answers.
