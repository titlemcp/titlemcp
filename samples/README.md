# TitleMCP Samples

This folder contains runnable examples for using TitleMCP from a local checkout.

## Franklin County Auditor with Ollama

See [franklin_county_ollama](franklin_county_ollama/) for a sample that starts an
MCP server exposing `franklin_county_auditor_search`, connects to it from an
Ollama client, and logs the model/tool exchange.

## Montgomery County Auditor with Ollama

See [montgomery_auditor_ollama](montgomery_auditor_ollama/) for a sample that
starts an MCP server exposing `montgomery_county_auditor_search`, connects to it
from an Ollama client, and logs the model/tool exchange. Montgomery runs the same
iasWorld platform as Franklin (a config entry in `titlemcp-us-oh-auditor`).
## Lucas County Auditor with Ollama

See [lucas_auditor_ollama](lucas_auditor_ollama/) for a sample that starts an MCP
server exposing `lucas_county_auditor_search` (Lucas County's AREIS / iasWorld
auditor site), connects to it from an Ollama client, and logs the model/tool
exchange.

## Lake County Auditor with Ollama

See [lake_auditor_ollama](lake_auditor_ollama/) for a sample that starts an MCP
server exposing `lake_county_auditor_search` (Lake County's unified iasWorld
`realprop` search), connects to it from an Ollama client, and logs the model/tool
exchange.

## Butler County Auditor with Ollama

See [butler_auditor_ollama](butler_auditor_ollama/) for a sample that starts an
MCP server exposing `butler_county_auditor_search` (the same shared iasWorld
platform as Franklin, with alphanumeric parcels), connects to it from an Ollama
client, and logs the model/tool exchange.

## HOA Contact Search with Ollama

See [hoa_serpapi_ollama](hoa_serpapi_ollama/) for a sample that asks Ollama a
natural HOA contact lookup question and verifies it triggers
`hoa_contact_search`.

## OFAC Sanctions Screening with Ollama

See [ofac_ollama](ofac_ollama/) for a sample that asks Ollama to run the sanctions
check on a closing file's parties and verifies it triggers `ofac_screen_parties`.

## Mortgage Release Search with Ollama

See [mortgage_release_ollama](mortgage_release_ollama/) for a sample that asks
Ollama whether a paid-off mortgage was released and verifies it triggers
`mortgage_release_search`.

## PACER Bankruptcy Search with Ollama

See [pacer_ollama](pacer_ollama/) for a sample that asks Ollama a natural
bankruptcy search question and verifies it triggers `pacer_bankruptcy_search`.
