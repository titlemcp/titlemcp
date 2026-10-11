# titlemcp-us-tn-tax

Tennessee county property tax status for TitleMCP. The connector
`us-tn-shelby-tax` (kind `tax_authority`) answers `property_tax_status_search`
for parcels in Shelby County.

## Source

The Shelby County Trustee's [Tax Query](https://apps2.shelbycountytrustee.com/)
answers from JSON endpoints, the ones its own pages call. It needs no
credential. For a parcel it lists each year's county bill it holds:
- the amount billed, paid and still owed;
- interest, fees and court, attorney and other costs;
- the delinquency date;
- tax sale and special condition flags.

The Tax Query gives no date for its data, so every answer says to confirm with
the Trustee.

The server needs TLS legacy renegotiation, which OpenSSL 3 refuses by default.
The client allows it for this host only and still verifies the certificate.

## City tax

The Trustee collects Shelby County's property tax. City property tax, such as
the City of Memphis's, isn't in these bills. The plan's second step is to
confirm it with the city.

## Parcels

A parcel number is written like `092007 00072`: the block, then the parcel
within it. The Trustee stores it padded (`092007  00072`), and the connector
accepts any spacing or dashes. A number written without them is split before
its last five or six characters (`00072`, `A00001`). If both splits are
parcels, the number is ambiguous and nothing is returned.

## Status

The Trustee says county tax becomes due the first Monday in October and can be
paid through the last day of February without interest. From the delinquency
date the Trustee shows, 1.5% interest is added each month
(Tenn. Code Ann. § 67-5-2010). Each year's date here is the last day before
that delinquency date. So:
- a balance after that date is `past_due`;
- a balance on an earlier year is `past_due` too;
- a parcel set for tax sale is noted.

The Trustee's billing figures also count days past due, but from the bill date
in August, so they aren't used.

Bills the connector can't read leave the whole answer `unknown`, never `paid`:
a bill without a year or balance, a bill whose two balances disagree, or bills
in the Tax Query's second bill group, which no parcel checked so far has used.

## Install

```bash
python -m pip install -e packages/titlemcp
python -m pip install -e packages/jurisdictions/us/tn/tax
```

## Tests

```bash
python -m unittest discover -s packages/jurisdictions/us/tn/tax/tests -v
```

The fixtures are invented and shaped like the Tax Query's answers.
