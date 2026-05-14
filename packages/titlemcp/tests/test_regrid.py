from __future__ import annotations

import unittest
from typing import Any

from title_mcp.domain.models import Jurisdiction
from title_mcp.settings import TitleMCPSettings
from title_mcp.sources import SourceKind, SourceQuery, SourceResultStatus
from title_mcp.sources.regrid import (
    RegridParcelLookupRecord,
    RegridParcelQueryService,
    RegridParcelSourceConnector,
    _redacted_proxy_map,
    _search_query_variants,
    generate_regrid_headers,
)


class RegridTests(unittest.IsolatedAsyncioTestCase):
    def test_generated_headers_look_browser_like(self) -> None:
        headers = generate_regrid_headers()

        self.assertIn("User-Agent", headers)
        self.assertIn("sec-ch-ua", headers)
        self.assertEqual(headers["upgrade-insecure-requests"], "1")

    def test_service_uses_smart_proxy_pool_and_cookie(self) -> None:
        service = RegridParcelQueryService(
            smart_proxy="user:pass@proxy.example",
            proxy_port_start=10001,
            proxy_port_end=10003,
            max_proxy_attempts=2,
            session=_FakeRegridSession(),
        )

        self.assertEqual(len(service.proxies), 3)
        self.assertEqual(service.max_proxy_attempts, 2)
        self.assertEqual(service.cookies["_session_id"], "cookie-123")
        self.assertIn(":10001", service.proxies[0]["http"])
        self.assertFalse(service.session.trust_env)

    def test_redacted_proxy_map_hides_credentials_and_ignores_env_proxy_keys(self) -> None:
        redacted = _redacted_proxy_map(
            {
                "http": "http://user:pass@proxy.example:10001",
                "https": "https://user:pass@proxy.example:10001",
                "title_mcp_smart": "user:pass@proxy.example",
            }
        )

        self.assertEqual(
            redacted,
            {
                "http": "http://***:***@proxy.example:10001",
                "https": "https://***:***@proxy.example:10001",
            },
        )

    def test_search_query_variants_try_comma_free_address_first(self) -> None:
        variants = _search_query_variants("1150 Glenn Ave, Columbus, OH")

        self.assertEqual(
            variants,
            [
                "1150 Glenn Ave Columbus OH",
                "1150 Glenn Ave",
                "1150 Glenn Ave, Columbus, OH",
            ],
        )

    def test_lookup_uses_comma_free_search_variant_first(self) -> None:
        session = _CommaSensitiveRegridSession()
        service = RegridParcelQueryService(
            smart_proxy="user:pass@proxy.example",
            proxy_port_start=10001,
            proxy_port_end=10001,
            session=session,
        )

        record = service.lookup("1150 Glenn Ave, Columbus, OH")

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.source["search_query_used"], "1150 Glenn Ave Columbus OH")
        self.assertEqual(session.search_queries, ["1150 Glenn Ave Columbus OH"])

    def test_service_lookup_merges_search_result_with_detail(self) -> None:
        service = RegridParcelQueryService(
            smart_proxy="user:pass@proxy.example",
            proxy_port_start=10001,
            proxy_port_end=10001,
            session=_FakeRegridSession(),
        )

        record = service.lookup("1150 Glenn Ave")

        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.path, "/us/oh/franklin/example")
        self.assertEqual(record.fields["parcelnumb"], "03000052600")
        self.assertEqual(record.geometry["type"], "Polygon")

    async def test_source_requires_smart_proxy_configuration(self) -> None:
        connector = RegridParcelSourceConnector(
            settings=TitleMCPSettings(
                smart_proxy=None,
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
                kind=SourceKind.VENDOR_API,
                criteria={"address": "1150 Glenn Ave"},
            )
        )

        self.assertEqual(result.status, SourceResultStatus.REQUIRES_CONFIGURATION)
        self.assertIn("TITLE_MCP_SMART_PROXY", result.warnings[0])

    async def test_source_returns_structured_record_with_fake_service(self) -> None:
        connector = RegridParcelSourceConnector(service=_FakeRegridService())

        result = await connector.query(
            SourceQuery(
                jurisdiction=Jurisdiction(country="US"),
                kind=SourceKind.VENDOR_API,
                criteria={"address": "1150 Glenn Ave"},
            )
        )

        self.assertEqual(result.status, SourceResultStatus.SUCCEEDED)
        self.assertEqual(result.records[0]["schema_name"], "title_mcp.parcel_record")
        self.assertEqual(result.records[0]["record_type"], "parcel")
        self.assertEqual(result.records[0]["identifiers"]["parcel_number"], "03000052600")
        self.assertEqual(result.records[0]["site"]["address_display"], "1150 GLENN AVE")
        self.assertEqual(result.records[0]["jurisdiction"]["county"], "Franklin")
        self.assertEqual(result.records[0]["land_use"]["use_code"], "510")
        self.assertEqual(
            result.records[0]["source_specific"]["regrid"]["fields"]["parcelnumb"],
            "03000052600",
        )
        self.assertTrue(result.metadata["smart_proxy_enabled"])


class _FakeRegridResponse:
    def __init__(
        self,
        payload: Any,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text if text is not None else ""

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._payload


class _FakeRegridSession:
    trust_env = True

    def head(self, *args: Any, **kwargs: Any) -> _FakeRegridResponse:
        return _FakeRegridResponse({}, headers={"Set-Cookie": "_session_id=cookie-123; path=/"})

    def get(self, url: str, *args: Any, **kwargs: Any) -> _FakeRegridResponse:
        if url.endswith("search.json"):
            return _FakeRegridResponse(
                [
                    {
                        "label": "1150 Glenn Ave",
                        "path": "/us/oh/franklin/example",
                    }
                ]
            )
        return _FakeRegridResponse(
            {
                "fields": {
                    "parcelnumb": "03000052600",
                    "address": "1150 GLENN AVE",
                    "county": "Franklin County",
                    "state2": "OH",
                    "usecode": "510",
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        )


class _CommaSensitiveRegridSession(_FakeRegridSession):
    def __init__(self) -> None:
        self.search_queries: list[str] = []

    def get(self, url: str, *args: Any, **kwargs: Any) -> _FakeRegridResponse:
        params = kwargs.get("params") or {}
        query = params.get("query")
        if url.endswith("search.json"):
            self.search_queries.append(query)
            if "," in query:
                return _FakeRegridResponse(
                    {},
                    status_code=503,
                    text='{ "status": "error", "code": "503", "message": "Service Unavailable" }',
                )
        return super().get(url, *args, **kwargs)


class _FakeRegridService:
    def lookup(self, address: str) -> RegridParcelLookupRecord:
        return RegridParcelLookupRecord(
            source={
                "source_id": RegridParcelSourceConnector.source_id,
                "source_name": "Regrid Parcel Search",
                "source_url": "https://app.regrid.com/example.json",
                "retrieved_at": "2026-05-14T18:00:00+00:00",
                "smart_proxy_enabled": True,
            },
            query={"address": address},
            label="1150 Glenn Ave",
            path="/us/oh/franklin/example",
            fields={
                "parcelnumb": "03000052600",
                "parcelnumb_no_formatting": "03000052600",
                "address": "1150 GLENN AVE",
                "scity": "GRANDVIEW HEIGHTS",
                "county": "Franklin County",
                "state2": "OH",
                "szip": "43212",
                "usecode": "510",
                "usedesc": "SINGLE FAMILY DWELLING, PLATTED LOT",
                "landval": 290900.0,
                "improvval": 427600.0,
                "parval": 718500.0,
                "yearbuilt": 1903,
                "area_building": 2843,
                "lat": "39.979984",
                "lon": "-83.053998",
            },
            geometry={"type": "Polygon", "coordinates": []},
            raw={"path": "/us/oh/franklin/example"},
        )


if __name__ == "__main__":
    unittest.main()
