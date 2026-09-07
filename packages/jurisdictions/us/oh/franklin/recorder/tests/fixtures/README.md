# Fixtures

`name_search.json` is a real `@kofile/FETCH_DOCUMENTS_FULFILLED/v6` response
from Franklin County, trimmed and de-identified.

**Kept verbatim**, because the tests turn on them: parcel numbers, the two
near-identical subdivision names, document types, recording dates, instrument
numbers, search-highlight markup, and the institutions named as lenders and
nominees.

**Changed**: the natural persons. Every personal-name token is replaced with an
invented one, consistently, so grantor and grantee relationships still hold.

**Removed**: `ocrText`, `highlights`, `thumbnail`, and `downloadLink`. The OCR
text is the scanned page, carrying names in arbitrary order and mailing
addresses, and no name-based replacement reaches into it reliably. Nothing
reads those fields.

County records are public. That is not a reason to keep a private individual's
property history in a public test fixture.
