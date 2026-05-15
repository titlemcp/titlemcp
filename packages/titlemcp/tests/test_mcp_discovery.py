from __future__ import annotations

import asyncio
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from starlette.testclient import TestClient

from title_mcp.mcp.server import create_mcp_server
from title_mcp.mcp.tool_catalog import _public_parcel_lookup_result
from title_mcp.settings import TitleMCPSettings


class ToolCatalogRouteTests(unittest.TestCase):
    def test_root_lists_tools_with_descriptions_and_annotations(self) -> None:
        settings = TitleMCPSettings(
            app_name="Test Title MCP",
            environment="test",
            log_json=False,
            mcp_transport="streamable-http",
            state_backend="memory",
            load_entry_point_toolsets=False,
        )
        server = create_mcp_server(settings)

        with TestClient(server.streamable_http_app()) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        catalog = response.json()
        self.assertEqual(catalog["name"], "Test Title MCP")
        self.assertEqual(catalog["mcp"]["endpoint"], "/mcp")
        self.assertEqual(catalog["mcp"]["url"], "http://testserver/mcp")
        self.assertGreater(catalog["tool_count"], 0)
        self.assertGreater(catalog["resource_count"], 0)
        self.assertGreater(catalog["prompt_count"], 0)

        tools = {tool["name"]: tool for tool in catalog["tools"]}
        self.assertIn("hoa_contact_search", tools)
        self.assertIn("parcel_lookup", tools)
        self.assertNotIn("regrid_parcel_lookup", tools)

        hoa_tool = tools["hoa_contact_search"]
        self.assertEqual(hoa_tool["title"], "HOA Contact Search")
        self.assertIn("Search for HOA contact information", hoa_tool["description"])
        self.assertTrue(hoa_tool["annotations"]["readOnlyHint"])
        self.assertTrue(hoa_tool["annotations"]["openWorldHint"])
        self.assertFalse(hoa_tool["annotations"]["destructiveHint"])
        self.assertIn("hoa_name", {parameter["name"] for parameter in hoa_tool["parameters"]})
        self.assertIn("input_schema", hoa_tool)

        parcel_tool = tools["parcel_lookup"]
        self.assertEqual(parcel_tool["title"], "Parcel Lookup")
        self.assertIn("Lookup parcel information by address", parcel_tool["description"])
        self.assertNotIn("Regrid", parcel_tool["title"])
        self.assertNotIn("Regrid", parcel_tool["description"])

        workflow_tool = tools["start_title_workflow"]
        self.assertFalse(workflow_tool["annotations"]["readOnlyHint"])
        self.assertFalse(workflow_tool["annotations"]["idempotentHint"])

        resources = {resource["uri"]: resource for resource in catalog["resources"]}
        self.assertIn("titlemcp://server/info", resources)
        self.assertIn("titlemcp://tools/catalog", resources)

        templates = {
            template["uriTemplate"]: template for template in catalog["resource_templates"]
        }
        self.assertIn("titlemcp://tools/{tool_name}", templates)

        prompts = {prompt["name"]: prompt for prompt in catalog["prompts"]}
        self.assertIn("parcel_lookup_review", prompts)
        self.assertIn("sample_parcel_lookup", prompts)
        self.assertIn("sample_hoa_contact_search", prompts)
        self.assertIn("sample_bankruptcy_search", prompts)
        self.assertIn("sample_franklin_county_auditor_search", prompts)
        self.assertIn("title_workflow_intake", prompts)

    def test_root_prefills_inspector_url_when_configured(self) -> None:
        settings = TitleMCPSettings(
            app_name="Test Title MCP",
            environment="test",
            log_json=False,
            mcp_transport="streamable-http",
            state_backend="memory",
            load_entry_point_toolsets=False,
            inspector_url="http://localhost:6274/?MCP_PROXY_AUTH_TOKEN=test-token",
            inspector_backend_url="http://titlemcp:8000/mcp",
        )
        server = create_mcp_server(settings)

        with TestClient(server.streamable_http_app()) as client:
            response = client.get("/")

        self.assertEqual(response.status_code, 200)
        inspector = response.json()["inspector"]
        self.assertEqual(inspector["transport"], "streamable-http")
        self.assertEqual(inspector["backend_url"], "http://titlemcp:8000/mcp")

        query = parse_qs(urlsplit(inspector["url"]).query)
        self.assertEqual(query["MCP_PROXY_AUTH_TOKEN"], ["test-token"])
        self.assertEqual(query["transport"], ["streamable-http"])
        self.assertEqual(query["serverUrl"], ["http://titlemcp:8000/mcp"])

    def test_health_routes_report_status(self) -> None:
        settings = TitleMCPSettings(
            app_name="Test Title MCP",
            environment="test",
            log_json=False,
            mcp_transport="streamable-http",
            state_backend="memory",
            load_entry_point_toolsets=False,
        )
        server = create_mcp_server(settings)

        with TestClient(server.streamable_http_app()) as client:
            health = client.get("/healthz")
            ready = client.get("/readyz")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")

    def test_inspector_resources_and_prompts_are_readable(self) -> None:
        settings = TitleMCPSettings(
            app_name="Test Title MCP",
            environment="test",
            log_json=False,
            mcp_transport="streamable-http",
            state_backend="memory",
            load_entry_point_toolsets=False,
        )
        server = create_mcp_server(settings)

        async def inspect_server() -> None:
            resource_uris = {str(resource.uri) for resource in await server.list_resources()}
            self.assertIn("titlemcp://server/info", resource_uris)
            self.assertIn("titlemcp://server/runtime", resource_uris)
            self.assertIn("titlemcp://tools/catalog", resource_uris)
            self.assertIn("titlemcp://workflows/kinds", resource_uris)

            template_uris = {
                str(template.uriTemplate) for template in await server.list_resource_templates()
            }
            self.assertIn("titlemcp://tools/{tool_name}", template_uris)

            contents = list(await server.read_resource("titlemcp://tools/catalog"))
            tool_catalog = json.loads(contents[0].content)
            tool_names = {tool["name"] for tool in tool_catalog["tools"]}
            self.assertIn("parcel_lookup", tool_names)

            tool_detail = list(await server.read_resource("titlemcp://tools/parcel_lookup"))
            parcel_detail = json.loads(tool_detail[0].content)
            self.assertEqual(parcel_detail["title"], "Parcel Lookup")

            prompts = {prompt.name: prompt for prompt in await server.list_prompts()}
            self.assertIn("parcel_lookup_review", prompts)
            self.assertIn("sample_parcel_lookup", prompts)
            self.assertIn("sample_hoa_contact_search", prompts)
            rendered = await server.get_prompt(
                "parcel_lookup_review",
                {"address": "1150 Glenn Ave, Columbus, OH"},
            )
            self.assertIn("parcel_lookup", rendered.messages[0].content.text)

            sample = await server.get_prompt(
                "sample_parcel_lookup",
                {
                    "address": "1150 Glenn Ave, Columbus, OH",
                    "summarize": True,
                },
            )
            self.assertIn("I need parcel data for a property", sample.messages[0].content.text)
            self.assertNotIn("Regrid", sample.messages[0].content.text)

            hoa_sample = await server.get_prompt(
                "sample_hoa_contact_search",
                {"hoa_name": "Example Woods HOA", "state": "Ohio"},
            )
            self.assertIn("I need contact details for an HOA", hoa_sample.messages[0].content.text)

            bankruptcy_sample = await server.get_prompt(
                "sample_bankruptcy_search",
                {"scenario": "business", "business_name": "Example Holdings LLC"},
            )
            self.assertIn(
                "Example Holdings LLC",
                bankruptcy_sample.messages[0].content.text,
            )

        asyncio.run(inspect_server())

    def test_server_configures_transport_security_from_settings(self) -> None:
        settings = TitleMCPSettings(
            log_json=False,
            mcp_allowed_hosts="localhost:*,127.0.0.1:*",
            mcp_allowed_origins="http://localhost:*,http://127.0.0.1:*",
        )
        server = create_mcp_server(settings)

        security = server.settings.transport_security
        self.assertIsNotNone(security)
        assert security is not None
        self.assertTrue(security.enable_dns_rebinding_protection)
        self.assertEqual(security.allowed_hosts, ["localhost:*", "127.0.0.1:*"])
        self.assertEqual(
            security.allowed_origins,
            ["http://localhost:*", "http://127.0.0.1:*"],
        )

    def test_public_parcel_lookup_result_hides_provider_details(self) -> None:
        public = _public_parcel_lookup_result(
            {
                "source_id": "regrid-parcel-search",
                "status": "succeeded",
                "citations": [
                    {
                        "label": "Regrid Parcel Search",
                        "uri": "https://app.regrid.com/example.json",
                    }
                ],
                "warnings": ["Regrid parcel lookup failed: example"],
                "records": [
                    {
                        "source": {
                            "source_id": "regrid-parcel-search",
                            "source_name": "Regrid Parcel Search",
                            "source_url": "https://app.regrid.com/example.json",
                        },
                        "source_specific": {
                            "regrid": {"schema_name": "title_mcp.regrid_parcel_lookup"}
                        },
                    }
                ],
            }
        )

        self.assertEqual(public["source_id"], "parcel-lookup")
        self.assertEqual(public["citations"][0]["label"], "Parcel Lookup")
        self.assertIsNone(public["citations"][0]["uri"])
        self.assertEqual(public["warnings"], ["Parcel lookup failed: example"])
        self.assertEqual(public["records"][0]["source"]["source_id"], "parcel-lookup")
        self.assertEqual(public["records"][0]["source"]["source_name"], "Parcel Lookup")
        self.assertIsNone(public["records"][0]["source"]["source_url"])
        self.assertNotIn("source_specific", public["records"][0])


if __name__ == "__main__":
    unittest.main()
