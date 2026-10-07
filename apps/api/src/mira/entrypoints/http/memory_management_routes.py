"""Same-origin, paired endpoints for explicit local USER_STATEMENT management."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from mira.application.memory_management import (
    MemoryManagement,
    MemoryManagementAuthorizationError,
    MemoryManagementOutcomeUnknownError,
    MemoryManagementUnavailableError,
    MemoryManagementValidationError,
)
from mira.application.ports.memory_management import (
    MemoryManagementBackendBusyError,
    MemoryManagementBackendConflictError,
    MemoryManagementBackendEntryNotFoundError,
    MemoryManagementBackendLimitError,
    MemoryManagementBackendOperationIdConflictError,
    MemoryManagementBackendTextRejectedError,
    MemoryManagementBackendUnavailableError,
    MemoryManagementCommand,
    MemoryManagementOperation,
    MAX_MANAGEMENT_PAGE_ITEMS,
)
from mira.domain.memory import MemoryDeadlineExceededError, MemoryKind, MemoryRevisionChangedError
from mira.entrypoints.http.schemas import (
    ErrorResponse,
    MemoryManagementEntryView,
    MemoryManagementOperationRequest,
    MemoryManagementOperationView,
    MemoryManagementPageView,
    MemoryManagementStatusView,
)

router = APIRouter(
    prefix="/api/v1/memory-management",
    tags=["local memory management"],
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        404: {"model": ErrorResponse, "description": "Not Found"},
        409: {"model": ErrorResponse, "description": "Conflict"},
        422: {"model": ErrorResponse, "description": "Unprocessable Content"},
        503: {"model": ErrorResponse, "description": "Service Unavailable"},
    },
)

_ERROR_MESSAGES = {
    "memory_management_disabled": "Local memory management isn't enabled for this launch.",
    "memory_management_unavailable": "Local memory management is unavailable.",
    "memory_management_busy": "Local memory is busy. Check the last result before retrying.",
    "memory_management_timeout": (
        "The result is unknown. Reconcile this operation ID before starting another."
    ),
    "stale_revision": "Memory changed. Refresh the list and review the change.",
    "operation_id_conflict": "This operation ID was already used for a different request.",
    "operation_conflict": "This operation could not be applied.",
    "entry_not_found": "That memory entry isn't available in this scope.",
    "statement_ineligible": "This statement can't be saved to local memory.",
    "memory_store_full": "Local memory has reached its configured limit.",
    "invalid_request": "The request doesn't match the local memory contract.",
}


def _error(request: Request, code: str, status: int, *,
           current_revision: int | None = None) -> JSONResponse:
    body = {
        "code": code,
        "message": _ERROR_MESSAGES.get(code, _ERROR_MESSAGES["memory_management_unavailable"]),
        "request_id": getattr(request.state, "request_id", "unavailable"),
    }
    if current_revision is not None:
        body["current_revision"] = current_revision
    return JSONResponse(body, status_code=status)


def _manager(request: Request) -> MemoryManagement | None:
    manager = getattr(request.app.state, "memory_management", None)
    return manager if isinstance(manager, MemoryManagement) else None


async def _map_error(request: Request, error: BaseException,
                     manager: MemoryManagement | None, *,
                     mutation: bool = False) -> JSONResponse:
    if isinstance(error, MemoryRevisionChangedError):
        current_revision = None
        if manager is not None and manager.is_open:
            try:
                current_revision = (await manager.status()).revision
            except Exception:
                current_revision = None
        return _error(request, "stale_revision", 409, current_revision=current_revision)
    if isinstance(error, MemoryManagementBackendOperationIdConflictError):
        return _error(request, "operation_id_conflict", 409)
    if isinstance(error, MemoryManagementBackendEntryNotFoundError):
        return _error(request, "entry_not_found", 409)
    if isinstance(error, MemoryManagementBackendConflictError):
        return _error(request, "operation_conflict", 409)
    if isinstance(error, MemoryManagementBackendBusyError):
        return _error(request, "memory_management_busy", 503)
    if isinstance(error, MemoryDeadlineExceededError):
        code = "memory_management_timeout" if mutation else "memory_management_unavailable"
        return _error(request, code, 503)
    if isinstance(error, MemoryManagementOutcomeUnknownError):
        return _error(request, "memory_management_timeout", 503)
    if isinstance(error, MemoryManagementBackendTextRejectedError):
        return _error(request, "statement_ineligible", 422)
    if isinstance(error, MemoryManagementBackendLimitError):
        return _error(request, "memory_store_full", 409)
    if isinstance(error, MemoryManagementBackendUnavailableError):
        return _error(request, "memory_management_unavailable", 503)
    if isinstance(error, (MemoryManagementAuthorizationError, MemoryManagementUnavailableError,
                          MemoryManagementValidationError)):
        code = "invalid_request" if isinstance(error, MemoryManagementValidationError) else (
            "memory_management_unavailable")
        status = 422 if code == "invalid_request" else 503
        return _error(request, code, status)
    if isinstance(error, ValueError):
        return _error(request, "invalid_request", 422)
    return _error(request, "memory_management_unavailable", 503)


@router.get("/status", response_model=MemoryManagementStatusView)
async def memory_management_status(
    request: Request,
) -> MemoryManagementStatusView | JSONResponse:
    manager = _manager(request)
    enabled = bool(getattr(request.app.state, "memory_management_enabled", False))
    if not enabled or manager is None or not manager.is_open:
        return MemoryManagementStatusView(enabled=False, revision=None)
    try:
        status = await manager.status()
    except Exception as error:
        return await _map_error(request, error, manager)
    return MemoryManagementStatusView(enabled=status.enabled, revision=status.revision)


@router.get("/entries", response_model=MemoryManagementPageView)
async def list_memory_entries(
    request: Request,
    limit: int = Query(default=20, ge=1, le=MAX_MANAGEMENT_PAGE_ITEMS),
    cursor: str | None = Query(default=None, max_length=64),
) -> MemoryManagementPageView | JSONResponse:
    manager = _manager(request)
    if not getattr(request.app.state, "memory_management_enabled", False) or manager is None:
        return _error(request, "memory_management_disabled", 404)
    try:
        page = await manager.list_entries(limit=limit, cursor=cursor)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return await _map_error(request, error, manager)
    return MemoryManagementPageView(
        revision=page.revision,
        entries=[MemoryManagementEntryView(
            entry_id=item.entry_id,
            text=item.text,
            kind=item.kind.value,
            source="user_statement",
            source_version=item.source_version,
            recorded_at=item.recorded_at,
            active=item.active,
            forget_event_id=item.forget_event_id,
            forgotten_at=item.forgotten_at,
        ) for item in page.entries],
        next_cursor=page.next_cursor,
    )


@router.post("/operations", response_model=MemoryManagementOperationView)
async def apply_memory_operation(
    body: MemoryManagementOperationRequest, request: Request
) -> MemoryManagementOperationView | JSONResponse:
    manager = _manager(request)
    if not getattr(request.app.state, "memory_management_enabled", False) or manager is None:
        return _error(request, "memory_management_disabled", 404)
    try:
        command = MemoryManagementCommand(
            operation_id=str(body.operation_id),
            expected_revision=body.expected_revision,
            operation=MemoryManagementOperation(body.operation),
            confirmed=body.confirmed,
            text=body.text,
            kind=MemoryKind(body.kind) if body.kind is not None else None,
            entry_id=body.entry_id,
            forget_event_id=body.forget_event_id,
        )
        result = await manager.apply_operation(command)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        return await _map_error(request, error, manager, mutation=True)
    return MemoryManagementOperationView(
        status="committed",
        operation_id=result.operation_id,
        revision=result.revision,
        entry_id=result.entry_id,
        event_id=result.event_id,
        replayed=result.replayed,
    )
