"""Current compiler scope must be visible to the native model; no scope expansion."""
import json
import pytest

from mira.adapters.generation.direct_codex_responses import ResponsesRoute
from tests.contracts.test_native_chapter_wire import WireSession
from tests.contracts.test_native_photo_request_intent import image_runtime


@pytest.mark.asyncio
@pytest.mark.parametrize('route',list(ResponsesRoute))
@pytest.mark.parametrize('subject',['画面里加一个虚构行人','换成一只橘猫蹲在门口'])
async def test_enabled_native_image_tool_discloses_actual_subject_scope_before_any_job(route,subject):
    s=WireSession(route=route);images=image_runtime(s)
    try:
        result,state=await s.turn(subject,'这次能找的是空景。换成雨里的街道可以吗？')
        body=json.loads(s.requests[0].content)
        tool=next(t for t in body['tools'] if t['name']=='generate_story_image')
        assert 'no people or animals, including fictional ones' in tool['description']
        assert 'offer an empty-scene alternative' in tool['description']
        assert 'never silently substitute or spend usage' in tool['description']
        assert 'empty scenery/still-life' in body['instructions']
        assert 'people/animals (even fictional)' in body['instructions']
        assert result is None and not images.requests and len(s.requests)==1
    finally:await s.close()
