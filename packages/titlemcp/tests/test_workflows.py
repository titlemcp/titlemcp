from __future__ import annotations

import unittest

from title_mcp.adapters import create_default_adapter_registry
from title_mcp.domain.models import (
    Jurisdiction,
    OrderRef,
    ReviewDecision,
    ReviewStatus,
    WorkflowKind,
    WorkflowRequest,
    WorkflowStatus,
)
from title_mcp.state.memory import InMemoryWorkflowRepository
from title_mcp.workflows.engine import WorkflowEngine


class WorkflowEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.repository = InMemoryWorkflowRepository()
        self.engine = WorkflowEngine(
            repository=self.repository,
            adapters=create_default_adapter_registry(),
            auto_start=False,
        )
        await self.repository.initialize()

    async def test_workflow_pauses_for_human_review(self) -> None:
        record = await self.engine.create(
            WorkflowRequest(
                kind=WorkflowKind.MUNICIPAL_LIEN_SEARCH,
                order=OrderRef(file_number="2025-123"),
                jurisdiction=Jurisdiction(state="fl", county="Pinellas"),
                payload={"parcel_id": "12-34-56"},
                require_human_review=True,
            )
        )

        self.assertEqual(record.adapter_id, "florida")
        self.assertEqual(record.status, WorkflowStatus.NEEDS_HUMAN_REVIEW)
        self.assertIsNotNone(record.review)

        paused = await self.engine.run_once(record.id)

        assert paused is not None
        self.assertEqual(paused.status, WorkflowStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(paused.review.status, ReviewStatus.PENDING)

    async def test_approved_review_advances_to_external_wait(self) -> None:
        record = await self.engine.create(
            WorkflowRequest(
                kind=WorkflowKind.TAX_CERTIFICATE,
                order=OrderRef(file_number="2025-456"),
                jurisdiction=Jurisdiction(state="FL", county="Orange"),
                payload={"parcel_id": "A-100"},
                require_human_review=True,
            )
        )
        await self.engine.submit_review(
            record.id,
            decision=ReviewDecision.APPROVE,
            reviewer="Closer",
            notes="Looks good.",
        )
        completed = await self.engine.run_once(record.id)

        assert completed is not None
        self.assertEqual(completed.status, WorkflowStatus.WAITING_ON_EXTERNAL)
        self.assertTrue(all(task.status.value == "succeeded" for task in completed.tasks))

    async def test_public_records_uses_city_specific_adapter(self) -> None:
        record = await self.engine.create(
            WorkflowRequest(
                kind=WorkflowKind.PUBLIC_RECORDS_SEARCH,
                order=OrderRef(file_number="2025-789"),
                jurisdiction=Jurisdiction(
                    country="US",
                    state="MD",
                    county="Baltimore",
                    municipality="Baltimore City",
                ),
                payload={"party_name": "Sample Buyer"},
                require_human_review=True,
            )
        )

        self.assertEqual(record.adapter_id, "us-md-baltimore-city-public-records")
        self.assertEqual(record.jurisdiction.key, "US:MD:baltimore:baltimore-city")


if __name__ == "__main__":
    unittest.main()
