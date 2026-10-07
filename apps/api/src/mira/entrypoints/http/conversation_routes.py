"""Fixed-scope archive management behind the existing operator cookie/origin gate."""
from dataclasses import asdict
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from mira.application.conversation_archive import ConversationArchiveError
from mira.application.ports.memory_management import MemoryManagementCommand, MemoryManagementOperation
from mira.domain.memory import MemoryRevisionChangedError
from mira.application.ports.memory_management import (MemoryManagementBackendConflictError as MemoryConflictError,
    MemoryManagementBackendEntryNotFoundError as MemoryEntryNotFoundError,
    MemoryManagementBackendTextRejectedError as MemoryPrivacyError,
    MemoryManagementBackendOperationIdConflictError as MemoryManagementOperationIdConflictError)
from mira.entrypoints.http.schemas import (ConversationStatusView, ConversationSessionsView,
    ConversationPageView, ConversationSelectionRequest, ConversationOperationRequest,
    ConversationRevokeRequest, MemoryManagementOperationView, ErrorResponse)

router=APIRouter(prefix='/api/v1/conversations',tags=['paired conversation archive'],responses={code:{'model':ErrorResponse,'description':description} for code,description in
    ((400,'Bad Request'),(404,'Not Found'),(409,'Conflict'),(422,'Unprocessable Content'),(503,'Service Unavailable'))})


def _runtime(request):
    runtime=getattr(request.app.state,'conversation_runtime',None)
    if runtime is None:raise ConversationArchiveError('conversation_disabled')
    return runtime


def _error(request,error,*,mutation=False):
    if isinstance(error,MemoryRevisionChangedError): code,status='stale_revision',409
    elif isinstance(error,MemoryManagementOperationIdConflictError):code,status='operation_id_conflict',409
    elif isinstance(error,(ConversationArchiveError,MemoryConflictError,MemoryEntryNotFoundError)):code,status='conversation_operation_denied',409
    elif isinstance(error,(MemoryPrivacyError,ValueError)):code,status='conversation_input_rejected',422
    else:code,status=('conversation_write_outcome_unknown' if mutation else 'conversation_unavailable'),503
    return JSONResponse({'code':code,'message':(
        '结果不确定；请刷新核对，不要假设本机写入已撤销。' if mutation and status==503 else
        '会话档案暂不可用或已变化；请刷新核对。本机旧版本和已发送内容不会因此被物理删除。'),
        'request_id':getattr(request.state,'request_id','unavailable')},status_code=status)


@router.get('/status',response_model=ConversationStatusView)
async def status(request:Request):
    runtime=getattr(request.app.state,'conversation_runtime',None)
    return ConversationStatusView(**runtime.status()) if runtime else ConversationStatusView(enabled=False,persistence_status='disabled')


@router.get('/sessions',response_model=ConversationSessionsView)
async def sessions(request:Request,cursor:str|None=Query(default=None,max_length=64)):
    try:return await _runtime(request).list_sessions(cursor)
    except Exception as error:return _error(request,error)


@router.get('/entries',response_model=ConversationPageView)
async def entries(request:Request,session_id:str=Query(min_length=1,max_length=128),cursor:str|None=Query(default=None,max_length=64)):
    try:return await _runtime(request).page(session_id,cursor)
    except Exception as error:return _error(request,error)


@router.post('/selection',response_model=ConversationStatusView)
async def select(body:ConversationSelectionRequest,request:Request):
    try:return await _runtime(request).select(body.session_id,
        recall_consent=body.authorize_selected_provider_and_jev,google_consent=body.authorize_google_derived_speech)
    except Exception as error:return _error(request,error)


@router.post('/operations',response_model=MemoryManagementOperationView)
async def operation(body:ConversationOperationRequest,request:Request):
    try:
        command=MemoryManagementCommand(operation_id=str(body.operation_id),expected_revision=body.expected_revision,
            operation=MemoryManagementOperation(body.operation),confirmed=body.confirmed,
            text=body.text,entry_id=body.entry_id,forget_event_id=body.forget_event_id)
        result=await _runtime(request).apply(body.session_id,command)
        return MemoryManagementOperationView(**asdict(result))
    except Exception as error:return _error(request,error,mutation=True)


@router.post('/revoke',response_model=ConversationStatusView)
async def revoke(body:ConversationRevokeRequest,request:Request):
    try:
        runtime=_runtime(request);runtime.revoke()
        return runtime.status()
    except Exception as error:return _error(request,error)
