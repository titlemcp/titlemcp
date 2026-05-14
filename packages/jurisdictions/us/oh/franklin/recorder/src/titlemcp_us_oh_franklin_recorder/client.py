from __future__ import annotations

import json

from pydantic import BaseModel, Field
from websockets.asyncio.client import connect


class RecorderSearchQuery(BaseModel):
    party_name: str | None = None
    parcel_id: str | None = None
    instrument_number: str | None = None
    date_range: str | None = None


class RecorderDocumentHit(BaseModel):
    instrument_number: str | None = None
    recorded_date: str | None = None
    document_type: str | None = None
    grantor: str | None = None
    grantee: str | None = None
    raw: dict = Field(default_factory=dict)


class FranklinRecorderClient:
    def __init__(self, websocket_url: str) -> None:
        self.websocket_url = websocket_url

    async def search(self, query: RecorderSearchQuery) -> list[RecorderDocumentHit]:
        async with connect(self.websocket_url) as websocket:
            await websocket.send(json.dumps(self._build_message(query)))

            hits: list[RecorderDocumentHit] = []
            async for raw_message in websocket:
                payload = json.loads(raw_message)
                if payload.get("type") == "complete":
                    break
                if payload.get("type") == "result":
                    hits.append(self._hit_from_payload(payload))
            return hits

    def _build_message(self, query: RecorderSearchQuery) -> dict:
        return {
            "action": "search",
            "criteria": query.model_dump(exclude_none=True),
        }

    def _hit_from_payload(self, payload: dict) -> RecorderDocumentHit:
        return RecorderDocumentHit(
            instrument_number=payload.get("instrumentNumber"),
            recorded_date=payload.get("recordedDate"),
            document_type=payload.get("documentType"),
            grantor=payload.get("grantor"),
            grantee=payload.get("grantee"),
            raw=payload,
        )
