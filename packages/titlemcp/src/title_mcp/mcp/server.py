from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ResourceError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Prompt, Resource, ResourceTemplate, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse

from title_mcp.domain.models import WorkflowKind
from title_mcp.mcp.tool_catalog import register_core_tools
from title_mcp.mcp.toolsets import register_entry_point_toolsets
from title_mcp.observability import configure_logging
from title_mcp.platform import TitleMCPPlatform
from title_mcp.settings import TitleMCPSettings, get_settings


def create_mcp_server(
    settings: TitleMCPSettings | None = None,
    platform: TitleMCPPlatform | None = None,
) -> FastMCP:
    settings = settings or (platform.settings if platform else get_settings())
    configure_logging(settings.log_level, json_logs=settings.log_json)
    platform = platform or TitleMCPPlatform(settings=settings)

    mcp = FastMCP(
        settings.app_name,
        instructions=(
            "Tools coordinate title and real estate service workflows. "
            "They are review-first and do not make autonomous legal decisions."
        ),
        host=settings.mcp_host,
        port=settings.mcp_port,
        transport_security=_transport_security_settings(settings),
    )

    register_core_tools(mcp, platform)
    if settings.load_entry_point_toolsets:
        register_entry_point_toolsets(mcp, platform)
    register_inspector_support(mcp, settings)
    register_tool_catalog_route(mcp, settings, platform)
    return mcp


def _transport_security_settings(settings: TitleMCPSettings) -> TransportSecuritySettings | None:
    if not settings.mcp_dns_rebinding_protection:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    if not settings.mcp_allowed_hosts and not settings.mcp_allowed_origins:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=settings.mcp_allowed_hosts,
        allowed_origins=settings.mcp_allowed_origins,
    )


def register_tool_catalog_route(
    mcp: FastMCP,
    settings: TitleMCPSettings,
    mcp_platform: TitleMCPPlatform,
) -> None:
    """Expose a public HTTP tool catalog for browser and deployment checks."""

    @mcp.custom_route("/", methods=["GET"], name="tool_catalog", include_in_schema=False)
    async def tool_catalog(request: Request) -> JSONResponse:
        tools = await _catalog_tools(mcp)
        resources = await _catalog_resources(mcp)
        resource_templates = await _catalog_resource_templates(mcp)
        prompts = await _catalog_prompts(mcp)
        mcp_endpoint = _mcp_endpoint(mcp)
        mcp_url = settings.mcp_public_url or _request_mcp_url(request, mcp_endpoint)
        catalog: dict[str, Any] = {
            "name": settings.app_name,
            "environment": settings.environment,
            "mcp": {
                "transport": settings.mcp_transport,
                "endpoint": mcp_endpoint,
                "url": mcp_url,
            },
            "tool_count": len(tools),
            "tools": tools,
            "resource_count": len(resources) + len(resource_templates),
            "resources": resources,
            "resource_templates": resource_templates,
            "prompt_count": len(prompts),
            "prompts": prompts,
        }
        inspector = _inspector_catalog_entry(settings, mcp_url)
        if inspector:
            catalog["inspector"] = inspector
        return JSONResponse(catalog)

    @mcp.custom_route("/healthz", methods=["GET"], name="healthz", include_in_schema=False)
    async def healthz(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "name": settings.app_name,
                "environment": settings.environment,
            }
        )

    @mcp.custom_route("/readyz", methods=["GET"], name="readyz", include_in_schema=False)
    async def readyz(_request: Request) -> JSONResponse:
        try:
            await mcp_platform.initialize()
        except Exception as exc:
            return JSONResponse(
                {
                    "status": "error",
                    "name": settings.app_name,
                    "environment": settings.environment,
                    "error": str(exc),
                },
                status_code=503,
            )
        return JSONResponse(
            {
                "status": "ready",
                "name": settings.app_name,
                "environment": settings.environment,
            }
        )


async def _catalog_tools(mcp: FastMCP) -> list[dict[str, Any]]:
    tools = sorted(await mcp.list_tools(), key=lambda tool: tool.name)
    return [_tool_catalog_entry(tool) for tool in tools]


async def _catalog_resources(mcp: FastMCP) -> list[dict[str, Any]]:
    resources = sorted(await mcp.list_resources(), key=lambda resource: str(resource.uri))
    return [_model_catalog_entry(resource) for resource in resources]


async def _catalog_resource_templates(mcp: FastMCP) -> list[dict[str, Any]]:
    templates = sorted(
        await mcp.list_resource_templates(),
        key=lambda template: str(template.uriTemplate),
    )
    return [_model_catalog_entry(template) for template in templates]


async def _catalog_prompts(mcp: FastMCP) -> list[dict[str, Any]]:
    prompts = sorted(await mcp.list_prompts(), key=lambda prompt: prompt.name)
    return [_model_catalog_entry(prompt) for prompt in prompts]


def _model_catalog_entry(value: Resource | ResourceTemplate | Prompt) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True, exclude_none=True)


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def _public_runtime_settings(settings: TitleMCPSettings) -> dict[str, Any]:
    return {
        "app_name": settings.app_name,
        "environment": settings.environment,
        "log_level": settings.log_level,
        "state_backend": settings.state_backend,
        "mcp": {
            "transport": settings.mcp_transport,
            "host": settings.mcp_host,
            "port": settings.mcp_port,
            "public_url_configured": bool(settings.mcp_public_url),
            "dns_rebinding_protection": settings.mcp_dns_rebinding_protection,
            "allowed_hosts": settings.mcp_allowed_hosts,
            "allowed_origins": settings.mcp_allowed_origins,
        },
        "entry_points": {
            "capabilities": settings.load_entry_point_capabilities,
            "adapters": settings.load_entry_point_adapters,
            "sources": settings.load_entry_point_sources,
            "vendors": settings.load_entry_point_vendors,
            "toolsets": settings.load_entry_point_toolsets,
            "plugins": settings.load_entry_point_plugins,
        },
        "configured_integrations": {
            "parcel_lookup": bool(settings.smart_proxy),
            "hoa_contact_search": bool(settings.serpapi_api_key),
            "pacer_bankruptcy_search": bool(settings.pacer_username and settings.pacer_password),
            "aws_textract": bool(settings.aws_region and settings.textract_s3_bucket),
        },
        "background_worker_concurrency": settings.background_worker_concurrency,
        "default_human_review_required": settings.default_human_review_required,
    }


def register_inspector_support(
    mcp: FastMCP,
    settings: TitleMCPSettings,
) -> None:
    """Expose MCP resources and prompts that make Inspector exploration useful."""

    @mcp.resource(
        "titlemcp://server/info",
        name="server_info",
        title="Server Info",
        description="High-level MCP server metadata, counts, and advertised capabilities.",
        mime_type="application/json",
    )
    async def server_info() -> str:
        return _json_text(
            {
                "name": settings.app_name,
                "environment": settings.environment,
                "mcp": {
                    "transport": settings.mcp_transport,
                    "endpoint": _mcp_endpoint(mcp),
                    "public_url": settings.mcp_public_url,
                },
                "capabilities": {
                    "tools": True,
                    "resources": True,
                    "prompts": True,
                    "health_routes": ["/healthz", "/readyz"],
                },
                "counts": {
                    "tools": len(await _catalog_tools(mcp)),
                    "resources": len(await _catalog_resources(mcp)),
                    "resource_templates": len(await _catalog_resource_templates(mcp)),
                    "prompts": len(await _catalog_prompts(mcp)),
                },
            }
        )

    @mcp.resource(
        "titlemcp://server/runtime",
        name="runtime_configuration",
        title="Runtime Configuration",
        description="Sanitized runtime configuration useful for debugging deployments.",
        mime_type="application/json",
    )
    async def runtime_configuration() -> str:
        return _json_text(_public_runtime_settings(settings))

    @mcp.resource(
        "titlemcp://tools/catalog",
        name="tool_catalog",
        title="Tool Catalog",
        description="Complete public tool catalog with descriptions, annotations, and schemas.",
        mime_type="application/json",
    )
    async def tool_catalog_resource() -> str:
        return _json_text({"tools": await _catalog_tools(mcp)})

    @mcp.resource(
        "titlemcp://tools/{tool_name}",
        name="tool_detail",
        title="Tool Detail",
        description="Detailed public schema and annotations for one tool.",
        mime_type="application/json",
    )
    async def tool_detail(tool_name: str) -> str:
        tools = {tool["name"]: tool for tool in await _catalog_tools(mcp)}
        if tool_name not in tools:
            raise ResourceError(f"Unknown tool: {tool_name}")
        return _json_text(tools[tool_name])

    @mcp.resource(
        "titlemcp://workflows/kinds",
        name="workflow_kinds",
        title="Workflow Kinds",
        description="Workflow kinds accepted by start_title_workflow and request tools.",
        mime_type="application/json",
    )
    async def workflow_kinds() -> str:
        return _json_text(
            {
                "workflow_kinds": [
                    {
                        "value": kind.value,
                        "title": _humanize_tool_name(kind.value),
                    }
                    for kind in sorted(WorkflowKind, key=lambda item: item.value)
                ]
            }
        )

    @mcp.prompt(
        name="title_workflow_intake",
        title="Title Workflow Intake",
        description="Draft a structured request for starting a title workflow.",
    )
    def title_workflow_intake(
        file_number: str,
        workflow_kind: str,
        state: str,
        county: str | None = None,
        property_address: str | None = None,
    ) -> str:
        return "\n".join(
            [
                "Prepare a concise title workflow intake request.",
                f"File number: {file_number}",
                f"Workflow kind: {workflow_kind}",
                f"State: {state}",
                f"County: {county or 'not provided'}",
                f"Property address: {property_address or 'not provided'}",
                "Use the start_title_workflow tool when the request is complete.",
                "Do not make legal or underwriting conclusions; flag review needs explicitly.",
            ]
        )

    @mcp.prompt(
        name="parcel_lookup_review",
        title="Parcel Lookup Review",
        description="Guide a reviewer through parcel lookup evidence.",
    )
    def parcel_lookup_review(address: str) -> str:
        return "\n".join(
            [
                "Use parcel_lookup for this address and review the returned parcel record.",
                f"Address: {address}",
                "Check parcel identifiers, owner names, site address, land use, valuation, "
                "and geometry.",
                "Call out missing or conflicting fields and keep human review required for "
                "title-impacting facts.",
            ]
        )

    @mcp.prompt(
        name="hoa_contact_review",
        title="HOA Contact Review",
        description="Guide a reviewer through HOA contact discovery evidence.",
    )
    def hoa_contact_review(hoa_name: str, state: str | None = None) -> str:
        return "\n".join(
            [
                "Use hoa_contact_search and review the returned candidates and fetched page "
                "evidence.",
                f"HOA name: {hoa_name}",
                f"State: {state or 'not provided'}",
                "Prefer official association or management-company pages over directories.",
                "Extract mailing address, website, phone numbers, emails, assessment/payment "
                "links, and evidence gaps.",
            ]
        )

    @mcp.prompt(
        name="sample_parcel_lookup",
        title="Sample Parcel Lookup",
        description="Sample natural-language parcel lookup prompt based on the Ollama sample.",
    )
    def sample_parcel_lookup(
        address: str = "100 Example Ave, Columbus, OH",
        summarize: bool = False,
    ) -> str:
        prompt = (
            "I need parcel data for a property. Can you look up the parcel record for "
            f"{address} and return the structured result?"
        )
        if summarize:
            return f"{prompt} After the lookup, give me a short summary too."
        return prompt

    @mcp.prompt(
        name="sample_hoa_contact_search",
        title="Sample HOA Contact Search",
        description="Sample natural-language HOA contact prompt based on the Ollama sample.",
    )
    def sample_hoa_contact_search(
        hoa_name: str = "Example Woods HOA",
        state: str | None = "Ohio",
        max_results: int = 10,
        extract: bool = True,
    ) -> str:
        location = f" in {state}" if state else ""
        prompt = (
            "I need contact details for an HOA. Find contact information for "
            f"{hoa_name}{location}. Return up to {max_results} candidate results."
        )
        if extract:
            prompt += (
                " After the tool returns, read records[0].first_result_page.text and "
                "extract the HOA's structured contact information as JSON with these "
                "keys: hoa_name, management_company, mailing_address, phone_numbers, "
                "email_addresses, website, source_url. Use null for fields you cannot "
                "confirm from the page text."
            )
        return prompt

    @mcp.prompt(
        name="sample_bankruptcy_search",
        title="Sample Bankruptcy Search",
        description="Sample natural-language bankruptcy search prompt based on the Ollama sample.",
    )
    def sample_bankruptcy_search(
        scenario: str = "person",
        first_name: str | None = "John",
        last_name: str = "Smith",
        business_name: str = "Example Holdings LLC",
        summarize: bool = False,
    ) -> str:
        if scenario == "business":
            prompt = (
                "Can you check bankruptcy records for the business "
                f"{business_name} and return the structured PACER result?"
            )
        else:
            name = " ".join(part for part in [first_name, last_name] if part)
            prompt = (
                "Can you check bankruptcy records for "
                f"{name} and return the structured PACER result?"
            )

        if summarize:
            return f"{prompt} After the lookup, give me a short summary too."
        return prompt

    @mcp.prompt(
        name="sample_franklin_county_auditor_search",
        title="Sample Franklin County Auditor Search",
        description="Sample Franklin County auditor prompt based on the Ollama sample.",
    )
    def sample_franklin_county_auditor_search(
        scenario: str = "parcel",
        parcel_id: str = "010-000123-00",
        address: str = "373 S HIGH ST, COLUMBUS, OH",
        owner_name: str = "CITY OF COLUMBUS",
        summarize: bool = False,
    ) -> str:
        if scenario == "address":
            prompt = (
                "I'm reviewing a Franklin County, Ohio property. Can you look up the "
                f"county auditor record for {address} and return the assessment record?"
            )
        elif scenario == "owner":
            prompt = (
                "I'm checking Franklin County, Ohio auditor records for an owner. "
                f"Can you search for {owner_name} and return any property assessment "
                "records you find?"
            )
        else:
            prompt = (
                "I'm reviewing a Franklin County, Ohio property. Can you look up the "
                f"county auditor record for parcel {parcel_id} and return the "
                "assessment record?"
            )

        if summarize:
            return (
                f"{prompt} After you find it, give me a short plain-English summary "
                "of the canonical assessment record too."
            )
        return prompt


def _mcp_endpoint(mcp: FastMCP) -> str:
    endpoint = getattr(mcp.settings, "streamable_http_path", "/mcp")
    return endpoint if endpoint.startswith("/") else f"/{endpoint}"


def _request_mcp_url(request: Request, endpoint: str) -> str:
    return urljoin(str(request.base_url), endpoint.lstrip("/"))


def _inspector_catalog_entry(
    settings: TitleMCPSettings, default_backend_url: str
) -> dict[str, str] | None:
    if not settings.inspector_url:
        return None
    transport = settings.mcp_transport
    backend_url = settings.inspector_backend_url or default_backend_url
    params = {"transport": transport}
    if transport in {"sse", "streamable-http"}:
        params["serverUrl"] = backend_url
    return {
        "transport": transport,
        "backend_url": backend_url,
        "url": _url_with_query(settings.inspector_url, params),
    }


def _url_with_query(url: str, params: dict[str, str]) -> str:
    parts = urlsplit(url)
    query_params = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_params.update(params)
    query = urlencode(query_params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, parts.fragment))


def _tool_catalog_entry(tool: Tool) -> dict[str, Any]:
    annotations = (
        tool.annotations.model_dump(mode="json", by_alias=True, exclude_none=True)
        if tool.annotations
        else {}
    )
    entry: dict[str, Any] = {
        "name": tool.name,
        "title": tool.title or annotations.get("title") or _humanize_tool_name(tool.name),
        "description": _normalize_description(tool.description),
        "annotations": annotations,
        "parameters": _parameter_summaries(tool.inputSchema),
        "input_schema": tool.inputSchema,
    }
    if tool.outputSchema:
        entry["output_schema"] = tool.outputSchema
    return entry


def _parameter_summaries(input_schema: dict[str, Any]) -> list[dict[str, Any]]:
    required = set(input_schema.get("required") or [])
    properties = input_schema.get("properties") or {}
    parameters: list[dict[str, Any]] = []
    for name, schema in properties.items():
        if not isinstance(schema, dict):
            continue
        parameters.append(
            {
                "name": name,
                "required": name in required,
                "type": _schema_type(schema),
                "description": _normalize_description(schema.get("description")),
            }
        )
    return parameters


def _schema_type(schema: dict[str, Any]) -> str | None:
    value = schema.get("type")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        return " | ".join(
            item.get("type", "object")
            for item in any_of
            if isinstance(item, dict) and item.get("type") != "null"
        )
    return None


def _normalize_description(value: Any) -> str:
    return " ".join(str(value or "").split())


def _humanize_tool_name(name: str) -> str:
    return name.replace("_", " ").title()


def main() -> None:
    settings = get_settings()
    server = create_mcp_server(settings)
    server.run(transport=settings.mcp_transport)


if __name__ == "__main__":
    main()
