from __future__ import annotations

import unittest
import urllib.error
import urllib.request
from email.message import Message

from title_mcp.domain.models import Jurisdiction
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus
from title_mcp.sources.hoa_serpapi import (
    HoaContactSearchQuery,
    HoaContactSerpApiSourceConnector,
    HoaPageFetch,
    SerpApiHoaContactClient,
    _fetch_page_text,
    build_hoa_contact_search_params,
    build_hoa_site_contact_search_params,
    hoa_contact_record_from_serpapi,
)


class HoaSerpApiTests(unittest.IsolatedAsyncioTestCase):
    def test_build_search_params_use_hoa_name_and_state_without_api_key(self) -> None:
        params = build_hoa_contact_search_params(
            HoaContactSearchQuery(hoa_name="Example Woods HOA", state="OH")
        )

        self.assertEqual(params["engine"], "google")
        self.assertIn('"Example Woods HOA"', params["q"])
        self.assertIn("contact", params["q"])
        self.assertIn("email", params["q"])
        self.assertIn("management company", params["q"])
        self.assertIn("OH", params["q"])
        self.assertIn("-site:facebook.com", params["q"])
        self.assertEqual(params["location"], "Ohio, United States")
        self.assertNotIn("api_key", params)

    def test_build_site_contact_params_restricts_to_official_domain(self) -> None:
        params = build_hoa_site_contact_search_params(
            HoaContactSearchQuery(hoa_name="Example Woods HOA", state="OH"),
            "examplewoodshoa.example",
        )

        self.assertIn("site:examplewoodshoa.example", params["q"])
        self.assertIn("management company", params["q"])
        self.assertNotIn("Example Woods HOA", params["q"])
        self.assertNotIn("api_key", params)

    def test_serpapi_response_maps_to_canonical_hoa_contact_record(self) -> None:
        record = hoa_contact_record_from_serpapi(
            query=HoaContactSearchQuery(hoa_name="Example Woods HOA", state="Ohio"),
            search_parameters={"engine": "google", "q": "Example Woods HOA"},
            data={
                "search_metadata": {
                    "id": "search-123",
                    "json_endpoint": "https://serpapi.com/searches/search-123.json?api_key=secret",
                },
                "knowledge_graph": {
                    "title": "Example Woods Homeowners Association",
                    "website": "https://examplewoods.example",
                    "phone": "(614) 555-0100",
                    "address": "123 Main St, Columbus, OH 43215",
                    "description": "Contact the board at board@examplewoods.example.",
                },
                "local_results": {
                    "places": [
                        {
                            "position": 1,
                            "title": "Example Woods HOA",
                            "address": "123 Main St, Columbus, OH",
                            "phone": "614-555-0100",
                            "website": "https://examplewoods.example/contact",
                        }
                    ]
                },
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Contact Example Woods HOA",
                        "link": "https://examplewoods.example/contact",
                        "snippet": "Email hoa@examplewoods.example or call 614.555.0100.",
                    }
                ],
            },
            duration_seconds=0.1,
        )

        self.assertEqual(record.schema_name, "title_mcp.hoa_contact_search")
        self.assertEqual(record.result_count, 2)
        self.assertEqual(record.best_match.email_addresses[0], "board@examplewoods.example")
        self.assertIn("hoa@examplewoods.example", record.email_addresses)
        self.assertIn("(614) 555-0100", record.phone_numbers)
        self.assertIn("123 Main St, Columbus, OH 43215", record.addresses)
        endpoint = record.source_specific["serpapi"]["searches"][0]["search_metadata"][
            "json_endpoint"
        ]
        self.assertIn("api_key=%2A%2A%2A", endpoint)

    def test_best_match_prefers_official_contact_pages_and_filters_url_ids(self) -> None:
        record = hoa_contact_record_from_serpapi(
            query=HoaContactSearchQuery(
                hoa_name="Tartan Fields Homeowners Association",
                state="Ohio",
            ),
            search_parameters={
                "engine": "google",
                "q": "Tartan Fields Homeowners Association contact",
            },
            data={
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Contact",
                        "link": "https://tartanfieldshoa.com/contact/",
                        "snippet": "About Tartan Fields Homeowners Association.",
                        "source": "Tartan Fields HOA",
                    },
                    {
                        "position": 2,
                        "title": "Tartan Fields Homeowners Association",
                        "link": (
                            "https://www.facebook.com/TartanTimesMagazine/posts/"
                            "tartan-fields-homeowners-association/1075755641372547/"
                        ),
                        "snippet": "Email at jgrooms@ohioequities.com.",
                        "source": "Facebook",
                    },
                    {
                        "position": 3,
                        "title": "Payments",
                        "link": "https://tartanfieldshoa.com/assessment/payments/",
                        "snippet": (
                            "Association Name: Tartan Fields Homeowners' Association. "
                            "Please contact Penny Wilson pwilson@ohioequities.com."
                        ),
                        "source": "Tartan Fields HOA",
                    },
                    {
                        "position": 4,
                        "title": "Tartan Fields Homeowners Association",
                        "link": (
                            "https://www.zoominfo.com/c/"
                            "tartan-fields-homeowners-association/1251896353"
                        ),
                        "snippet": "Phone number: (614) 939-8600 Website: www.tartanfieldshoa.com",
                        "source": "ZoomInfo",
                    },
                ]
            },
            duration_seconds=0.1,
        )

        assert record.best_match is not None
        self.assertEqual(
            record.best_match.website,
            "https://tartanfieldshoa.com/assessment/payments/",
        )
        self.assertIn("pwilson@ohioequities.com", record.email_addresses)
        self.assertIn("(614) 939-8600", record.phone_numbers)
        self.assertNotIn("10757556413", record.phone_numbers)
        self.assertNotIn("1251896353", record.phone_numbers)

    def test_client_refines_contact_search_to_selected_official_domain(self) -> None:
        session = _FakeSerpApiSession(
            [
                {
                    "organic_results": [
                        {
                            "position": 1,
                            "title": "Tartan Fields HOA: Home",
                            "link": "https://tartanfieldshoa.com/",
                            "snippet": "About Tartan Fields Homeowners Association.",
                            "source": "Tartan Fields HOA",
                        }
                    ]
                },
                {
                    "organic_results": [
                        {
                            "position": 1,
                            "title": "Payments",
                            "link": "https://tartanfieldshoa.com/assessment/payments/",
                            "snippet": (
                                "Please contact Penny Wilson "
                                "pwilson@ohioequities.com for questions."
                            ),
                            "source": "Tartan Fields HOA",
                        }
                    ]
                },
            ]
        )
        page_fetcher = _RecordingPageFetcher(
            HoaPageFetch(
                url="https://tartanfieldshoa.com/assessment/payments/",
                final_url="https://tartanfieldshoa.com/assessment/payments/",
                status_code=200,
                content_type="text/html; charset=utf-8",
                title="Tartan Fields HOA Payments",
                text=(
                    "Tartan Fields Homeowners' Association\n"
                    "Contact Penny Wilson pwilson@ohioequities.com or call "
                    "(614) 939-8600 for assessments and payments."
                ),
                text_length=140,
            )
        )
        client = SerpApiHoaContactClient(
            "secret-key",
            session=session,
            page_fetcher=page_fetcher,
        )

        record = client.hoa_contact_search(
            HoaContactSearchQuery(
                hoa_name="Tartan Fields Homeowners Association",
                state="Ohio",
            )
        )

        self.assertEqual(len(session.requests), 2)
        self.assertNotIn("site:tartanfieldshoa.com", session.requests[0]["params"]["q"])
        self.assertIn("site:tartanfieldshoa.com", session.requests[1]["params"]["q"])
        self.assertEqual(
            record.source_specific["serpapi"]["official_domain"],
            "tartanfieldshoa.com",
        )
        self.assertEqual(record.best_match.source_type, "site_result")
        self.assertEqual(record.email_addresses, ["pwilson@ohioequities.com"])
        self.assertEqual(
            page_fetcher.calls,
            ["https://tartanfieldshoa.com/assessment/payments/"],
        )
        assert record.first_result_page is not None
        self.assertEqual(record.first_result_page.status_code, 200)
        self.assertIn("pwilson@ohioequities.com", record.first_result_page.text)

    def test_client_skips_page_fetch_when_no_candidates_returned(self) -> None:
        session = _FakeSerpApiSession([{"organic_results": []}, {"organic_results": []}])
        page_fetcher = _RecordingPageFetcher(HoaPageFetch(url="unused"))
        client = SerpApiHoaContactClient(
            "secret-key",
            session=session,
            page_fetcher=page_fetcher,
        )

        record = client.hoa_contact_search(
            HoaContactSearchQuery(hoa_name="Empty HOA", state="Ohio")
        )

        self.assertEqual(page_fetcher.calls, [])
        self.assertIsNone(record.first_result_page)

    def test_fetch_page_text_strips_scripts_and_extracts_title(self) -> None:
        html = (
            "<!doctype html><html><head><title>Example HOA</title>"
            "<script>var x = 1;</script><style>body{color:red}</style></head>"
            "<body><h1>Example HOA</h1>"
            "<p>Email <a href='mailto:board@example.org'>board@example.org</a></p>"
            "<p>Call (614) 555-0100.</p></body></html>"
        )
        url = "https://example.org/contact"
        opener = _FakeUrlOpener({url: html.encode("utf-8")})
        original = urllib.request._opener  # type: ignore[attr-defined]
        urllib.request.install_opener(opener)
        try:
            fetched = _fetch_page_text(url, timeout=5.0)
        finally:
            urllib.request.install_opener(original)

        self.assertIsNone(fetched.error)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.title, "Example HOA")
        assert fetched.text is not None
        self.assertIn("board@example.org", fetched.text)
        self.assertIn("(614) 555-0100", fetched.text)
        self.assertNotIn("var x = 1", fetched.text)
        self.assertNotIn("color:red", fetched.text)

    def test_fetch_page_text_returns_error_on_failure(self) -> None:
        url = "https://example.invalid/never-resolves"

        def _boom(request, timeout):  # pragma: no cover - tiny inline opener
            raise urllib.error.URLError("no DNS")

        opener = _FakeUrlOpener({}, open_override=_boom)
        original = urllib.request._opener  # type: ignore[attr-defined]
        urllib.request.install_opener(opener)
        try:
            fetched = _fetch_page_text(url, timeout=1.0)
        finally:
            urllib.request.install_opener(original)

        self.assertIsNotNone(fetched.error)
        self.assertIsNone(fetched.status_code)
        self.assertIsNone(fetched.text)

    async def test_source_requires_serpapi_configuration(self) -> None:
        connector = HoaContactSerpApiSourceConnector(
            settings=TitleMCPSettings(
                serpapi_api_key=None,
                load_entry_point_adapters=False,
                load_entry_point_capabilities=False,
                load_entry_point_sources=False,
                load_entry_point_vendors=False,
                load_entry_point_toolsets=False,
            )
        )

        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.HOA,
                criteria={"hoa_name": "Example Woods HOA"},
            )
        )

        self.assertEqual(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertIn("TITLE_MCP_SERPAPI_API_KEY", result.warnings[0])

    async def test_source_returns_structured_hoa_record(self) -> None:
        connector = HoaContactSerpApiSourceConnector(client=_FakeHoaContactClient())

        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.HOA,
                criteria={"hoa_name": "Example Woods HOA", "state": "Ohio"},
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(result.records[0]["schema_name"], "title_mcp.hoa_contact_search")
        self.assertEqual(result.records[0]["email_addresses"], ["board@examplewoods.example"])
        self.assertEqual(result.metadata["email_count"], 1)
        self.assertEqual(result.citations[0].label, "SerpAPI Google Search API")


class _FakeHoaContactClient:
    def hoa_contact_search(self, query: HoaContactSearchQuery):
        return hoa_contact_record_from_serpapi(
            query=query,
            search_parameters={"engine": "google", "q": query.hoa_name},
            data={
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Example Woods HOA Contact",
                        "link": "https://examplewoods.example/contact",
                        "snippet": "Board email: board@examplewoods.example",
                    }
                ]
            },
            duration_seconds=0.01,
        )


class _FakeSerpApiResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeSerpApiSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def get(self, url, *, params, timeout):
        self.requests.append({"url": url, "params": dict(params), "timeout": timeout})
        return _FakeSerpApiResponse(self.responses.pop(0))


class _RecordingPageFetcher:
    def __init__(self, response: HoaPageFetch) -> None:
        self._response = response
        self.calls: list[str] = []

    def __call__(self, url: str) -> HoaPageFetch:
        self.calls.append(url)
        return self._response.model_copy(update={"url": url})


class _FakeHttpResponse:
    def __init__(
        self,
        *,
        body: bytes,
        url: str,
        status: int = 200,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        self._body = body
        self._url = url
        self.status = status
        headers = Message()
        headers["Content-Type"] = content_type
        self.headers = headers

    def __enter__(self) -> _FakeHttpResponse:
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def read(self, amount: int | None = None) -> bytes:
        if amount is None or amount >= len(self._body):
            return self._body
        return self._body[:amount]

    def geturl(self) -> str:
        return self._url


class _FakeUrlOpener:
    def __init__(self, payloads: dict[str, bytes], *, open_override=None) -> None:
        self._payloads = payloads
        self._open_override = open_override

    def open(self, request, data=None, timeout=None):
        if self._open_override is not None:
            return self._open_override(request, timeout)
        url = (
            request.full_url
            if isinstance(request, urllib.request.Request)
            else str(request)
        )
        return _FakeHttpResponse(body=self._payloads[url], url=url)


if __name__ == "__main__":
    unittest.main()
