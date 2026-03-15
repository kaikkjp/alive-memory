"""API endpoint handlers."""

from __future__ import annotations

from fastapi import APIRouter, Request

from alive_memory import AliveMemory, __version__
from alive_memory.server.models import (
    BackstoryRequest,
    CognitiveStateResponse,
    ConsolidateRequest,
    DayMomentResponse,
    DriveStateResponse,
    DriveUpdateRequest,
    HealthResponse,
    IntakeRequest,
    RecallContextResponse,
    RecallRequest,
    SelfModelResponse,
    SleepReportResponse,
    cognitive_state_to_response,
    drive_state_to_response,
    moment_to_response,
    recall_context_to_response,
    self_model_to_response,
    sleep_report_to_response,
)

router = APIRouter()


def _get_memory(request: Request) -> AliveMemory:
    return request.app.state.memory


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check."""
    return HealthResponse(status="ok", version=__version__)


@router.post("/intake", response_model=DayMomentResponse | None)
async def intake(body: IntakeRequest, request: Request):
    """Record an event. Returns a DayMoment if salient enough, null otherwise."""
    memory = _get_memory(request)
    result = await memory.intake(
        event_type=body.event_type,
        content=body.content,
        metadata=body.metadata,
        timestamp=body.timestamp,
    )
    if result is None:
        return None
    return moment_to_response(result)


@router.post("/recall", response_model=RecallContextResponse)
async def recall(body: RecallRequest, request: Request):
    """Retrieve context from hot memory."""
    memory = _get_memory(request)
    ctx = await memory.recall(
        query=body.query,
        limit=body.limit,
    )
    return recall_context_to_response(ctx)


@router.post("/consolidate", response_model=SleepReportResponse)
async def consolidate(body: ConsolidateRequest, request: Request):
    """Run memory consolidation (sleep cycle)."""
    memory = _get_memory(request)
    report = await memory.consolidate(
        whispers=body.whispers,
        depth=body.depth,
    )
    return sleep_report_to_response(report)


@router.get("/state", response_model=CognitiveStateResponse)
async def get_state(request: Request):
    """Get the current cognitive state."""
    memory = _get_memory(request)
    state = await memory.get_state()
    return cognitive_state_to_response(state)


@router.get("/identity", response_model=SelfModelResponse)
async def get_identity(request: Request):
    """Get the current self-model (identity)."""
    memory = _get_memory(request)
    model = await memory.get_identity()
    return self_model_to_response(model)


@router.post("/drives/{name}", response_model=DriveStateResponse)
async def update_drive(name: str, body: DriveUpdateRequest, request: Request):
    """Manually adjust a drive value."""
    memory = _get_memory(request)
    drives = await memory.update_drive(drive=name, delta=body.delta)
    return drive_state_to_response(drives)


@router.post("/backstory", response_model=DayMomentResponse)
async def inject_backstory(body: BackstoryRequest, request: Request):
    """Inject a backstory memory."""
    memory = _get_memory(request)
    result = await memory.inject_backstory(
        content=body.content,
        title=body.title,
    )
    return moment_to_response(result)
