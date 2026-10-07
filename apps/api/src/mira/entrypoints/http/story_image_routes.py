"""Exact qualified bytes; session authentication and current effect grant are mandatory."""
from uuid import UUID
from fastapi import APIRouter, Response
from mira.entrypoints.http.routes import ContainerDependency, Token
from mira.entrypoints.http.schemas import StoryImageResourceRequest, ErrorResponse

router=APIRouter(prefix='/api/v1', responses={
    400:{'model':ErrorResponse,'description':'Bad Request'},
    404:{'model':ErrorResponse,'description':'Not Found'},
    409:{'model':ErrorResponse,'description':'Conflict'},
    422:{'model':ErrorResponse,'description':'Unprocessable Content'}})

@router.post('/sessions/{session_id}/story-images/{resource_id}', response_class=Response,
    responses={200:{'content':{'image/png':{'schema':{'type':'string','format':'binary'}}}}})
async def story_image_resource(session_id: UUID, resource_id: UUID,
        body: StoryImageResourceRequest, token: Token, container: ContainerDependency):
    actor=container.sessions.get(str(session_id),token)
    data=await actor.story_image_resource(resource_id=str(resource_id),effect_id=str(body.effect_id),
        digest=body.digest,output_epoch=body.output_epoch,activity_seq=body.activity_seq,
        content_digest=body.content_digest)
    return Response(data,media_type='image/png',headers={'Cache-Control':'no-store',
        'X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'"})
