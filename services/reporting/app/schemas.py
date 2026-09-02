from pydantic import BaseModel, Field

from .models import Category, Status


class IssueCreate(BaseModel):
    category: Category
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(default="")
    building: str
    floor: str
    room: str | None = None
    equipment_name: str | None = None
    mobile_number: str = Field(min_length=8)
    ack_confirmed: bool


class IssueUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    building: str | None = None
    floor: str | None = None
    room: str | None = None
    equipment_name: str | None = None
    mobile_number: str | None = None


class TriageResultIn(BaseModel):
    """Written by the triage service."""

    severity: str
    urgency: str
    equipment_name: str | None = None
    duplicate_group_id: str | None = None
    duplicate_count: int | None = None
    # No longer a triage output (it lives in severity_rationale, docs/05); kept
    # optional so an admin-set value survives a re-triage instead of being reset.
    is_critical_system: bool | None = None


class StatusChange(BaseModel):
    status: Status
    detail: str | None = None


class CloseRequest(BaseModel):
    closed_by: str = "reporter"  # reporter | auto | admin
    resolution_type: str | None = None
    resolution_notes: str | None = None


class CancelRequest(BaseModel):
    reason: str


class SuggestDescriptionRequest(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    category: Category | None = None
    building: str | None = None
    floor: str | None = None
    existing_text: str | None = None


class SuggestDescriptionResponse(BaseModel):
    description: str | None = None
    confidence: float | None = None
    suggested_title: str | None = None
    title_confidence: float | None = None


class PhotoPreviewResponse(BaseModel):
    """Response of POST /issues/preview-photo-check — same shape as the
    verdict a real photo upload produces, but computed before the issue
    exists (docs/04-ai-integration.md §7)."""

    verdict: str
    confidence: float
    reason: str
    suggested_category: Category | None = None
    suggested_title: str | None = None
    suggested_description: str | None = None
