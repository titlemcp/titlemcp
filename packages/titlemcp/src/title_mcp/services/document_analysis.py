from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentAnalysisRequest(BaseModel):
    document_uri: str
    provider: str = "aws_textract"
    document_type_hint: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentAnalysisResult(BaseModel):
    provider: str
    document_uri: str
    extracted_text: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    requires_review: bool = True
    provider_job_id: str | None = None


class DocumentAnalysisService:
    """Provider abstraction for OCR and extraction.

    The default implementation records intent and returns a review-first placeholder. Production
    deployments can subclass this service or inject a plugin that calls AWS Textract or another OCR
    provider.
    """

    async def analyze(self, request: DocumentAnalysisRequest) -> DocumentAnalysisResult:
        return DocumentAnalysisResult(
            provider=request.provider,
            document_uri=request.document_uri,
            fields={
                "document_type_hint": request.document_type_hint,
                "metadata": request.metadata,
            },
            requires_review=True,
        )
