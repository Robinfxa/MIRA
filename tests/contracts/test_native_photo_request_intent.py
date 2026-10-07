"""Production serialization of natural photo-request guidance; offline only."""
import json
import pytest

from mira.adapters.generation.direct_codex_responses import ResponsesRoute
from mira.application.ports.generation_tools import GenerationToolCall
from mira.application.story_images import StoryImageRuntime, StoryImageAdmission
from tests.contracts.test_native_chapter_wire import WireSession
from tests.contracts.test_luna_tool_actor import ImageBackend
from tests.contracts.test_story_images import Decoder, Vision


def image_runtime(s):
    images=ImageBackend(fail=True)
    s.a._story_images=StoryImageRuntime(images,Vision('allow'),Decoder(),
        StoryImageAdmission('synthetic-only',True,timeout_seconds=1,authorized_custom_brief=True))
    s.a._story_images.bind_session('s')
    return images


def assert_intent_contract(body):
    text=body['instructions']
    assert '还有别的照片吗' in text and '别的给我看看' in text
    assert 'without requiring the word 生成' in text
    assert 'past photography experiences' in text
    assert 'existing pending job' in text and 'permanently contains only one photo' in text


@pytest.mark.asyncio
@pytest.mark.parametrize('route',list(ResponsesRoute))
@pytest.mark.parametrize('utterance',['还有别的照片吗','别的给我看看'])
async def test_actual_wire_natural_photo_request_uses_existing_enabled_tool_and_gates(route,utterance):
    s=WireSession(route=route);images=image_runtime(s)
    try:
        await s.turn('这张照片我看过了','这张灯塔照片可以慢慢看。')
        call=GenerationToolCall('image','generate_story_image',json.dumps({
            'brief':'An imaginary empty rainlit cafe window.','framing':'wide','lighting':'warm'}))
        r,state=await s.turn(utterance,call)
        assert r['status']=='failed' and r['reason']=='generation'
        assert len(images.requests)==1 and len(s.requests)==3
        body=json.loads(s.requests[-2].content);assert_intent_contract(body)
        definition=next(t for t in body['tools'] if t['name']=='generate_story_image')
        assert 'another photo in a photo-sharing context' in definition['description']
        assert '生成' in definition['description']
        continuation=json.loads(s.requests[-1].content)
        assert continuation['tools']==[] and continuation['tool_choice']=='none'
        assert_intent_contract(continuation)
    finally:await s.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('utterance',['你以前还拍过什么照片','他说“别的给我看看”','不想看别的照片','如果想看别的呢','还有别的照片吗'])
async def test_photo_words_without_native_call_do_not_start_or_invent_an_image(utterance):
    s=WireSession();images=image_runtime(s)
    try:
        r,state=await s.turn(utterance,'我们接着聊。')
        assert r is None and not images.requests
        assert_intent_contract(json.loads(s.requests[0].content))
    finally:await s.close()


@pytest.mark.asyncio
async def test_natural_request_with_disabled_images_keeps_tool_absent():
    s=WireSession()
    try:
        r,state=await s.turn('还有别的照片吗','这次暂时不能找新图，我们可以聊聊想看的风景。')
        body=json.loads(s.requests[0].content);assert_intent_contract(body)
        assert not any(t['name']=='generate_story_image' for t in body['tools'])
        assert r is None and len(s.requests)==1
    finally:await s.close()
