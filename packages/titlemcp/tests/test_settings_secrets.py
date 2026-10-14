from __future__ import annotations

import json
import os
import unittest
import unittest.mock
from typing import Any

from pydantic import SecretStr

from title_mcp.mcp.server import _public_runtime_settings
from title_mcp.settings import TitleMCPSettings, secret_value
from title_mcp.sources.hoa_serpapi import HoaContactSerpApiSourceConnector
from title_mcp.sources.pacer import PacerBankruptcySourceConnector
from title_mcp.state.factory import create_repository

# Invented values. None of them is a real credential.
FAKE_ENV = {
    "TITLE_MCP_PACER_USERNAME": "example-user",
    "TITLE_MCP_PACER_PASSWORD": "fake-pacer-password",
    "TITLE_MCP_SERPAPI_API_KEY": "fake-serpapi-key",
    "TITLE_MCP_ANTHROPIC_API_KEY": "fake-anthropic-key",
    "TITLE_MCP_SMART_PROXY": "proxyuser:fake-proxy-password@proxy.example",
    "TITLE_MCP_POSTGRES_DSN": "postgresql://dbuser:fake-db-password@db.example/title_mcp",
}
SECRET_PARTS = [
    "fake-pacer-password",
    "fake-serpapi-key",
    "fake-anthropic-key",
    "fake-proxy-password",
    "fake-db-password",
]


def _settings(**overrides: Any) -> TitleMCPSettings:
    with unittest.mock.patch.dict(os.environ, FAKE_ENV):
        return TitleMCPSettings(_env_file=None, **overrides)


class SettingsSecretTests(unittest.TestCase):
    def assertNoSecret(self, text: str) -> None:
        for part in SECRET_PARTS:
            self.assertNotIn(part, text)

    def test_printing_or_dumping_settings_hides_every_credential(self) -> None:
        settings = _settings()

        self.assertNoSecret(repr(settings))
        self.assertNoSecret(str(settings))
        self.assertNoSecret(json.dumps(settings.model_dump(mode="json")))

    def test_runtime_resource_says_what_is_configured_without_the_values(self) -> None:
        info = _public_runtime_settings(_settings())

        self.assertNoSecret(json.dumps(info))
        self.assertEqual(
            info["configured_integrations"],
            {
                "parcel_lookup": True,
                "hoa_contact_search": True,
                "pacer_bankruptcy_search": True,
                "aws_textract": False,
            },
        )

    def test_secret_value_reads_secrets_and_plain_strings(self) -> None:
        self.assertEqual(secret_value(SecretStr("abc")), "abc")
        self.assertEqual(secret_value("abc"), "abc")
        self.assertIsNone(secret_value(SecretStr("")))
        self.assertIsNone(secret_value(""))
        self.assertIsNone(secret_value(None))

    def test_connectors_receive_the_plain_values(self) -> None:
        settings = _settings()

        pacer = PacerBankruptcySourceConnector(settings=settings)._client_from_settings()
        assert pacer is not None
        self.assertEqual(pacer.password, "fake-pacer-password")

        serpapi = HoaContactSerpApiSourceConnector(settings=settings)._client_from_settings()
        assert serpapi is not None
        self.assertEqual(serpapi.api_key, "fake-serpapi-key")

        repository = create_repository(_settings(state_backend="postgres"))
        self.assertEqual(
            repository._dsn,  # type: ignore[attr-defined]
            "postgresql://dbuser:fake-db-password@db.example/title_mcp",
        )


if __name__ == "__main__":
    unittest.main()
