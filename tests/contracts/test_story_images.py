import asyncio
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from mira.domain.story_images import ImageProposal, parse_image_proposal, parse_generated_photo, ImageReservation
from mira.application.story_images import StoryImageRuntime, StoryImageAdmission, compile_image_intent
from mira.application.ports.media import GeneratedImage, CanonicalImage, MediaReviewObservation, PixelCheck
from mira.domain.models import SessionState, EffectKind
from mira.domain import transitions
from mira.application.compiler import compile_generated_media
from mira.bootstrap.character_story import ephemeral_character_factory


def story():
 return ephemeral_character_factory()(SessionState('session','client')).begin_input('turn',1)

def test_proposal_is_closed_and_compiles_only_released_fiction():
 a=parse_image_proposal({'schema':'mira.story-image-proposal.v1','scene_id':'cafe_rain_window','framing':'wide','lighting':'scene_default'})
 b=replace(a,scene_id='cafe_table_still_life')
 assert compile_image_intent(a,story()).specification != compile_image_intent(b,story()).specification
 for extra in ({'prompt':'secret'}, {'url':'https://example.com'}, {'resource_id':'fake'}, {'user_memory':'secret'}):
  with pytest.raises(ValueError):parse_image_proposal({**a.as_dict(),**extra})
 with pytest.raises(ValueError):compile_image_intent(replace(a,scene_id='unreleased_secret'),story())
 with pytest.raises(ValueError):compile_image_intent(a,None)


def test_generated_value_is_strict_and_reservation_only_post_seal():
 resource=str(uuid4());digest='a'*64
 assert parse_generated_photo('generated_story_photo:v1:'+resource+':'+digest)==(resource,digest)
 assert parse_generated_photo('generated_story_photo:v1:../../file:'+digest) is None
 state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='scene')
 reservation=ImageReservation('image','turn',1,1,0,'b'*64,'c'*64,'image-policy-v1',session_id='s')
 state=transitions.reserve_generated_media(state,reservation)
 state=transitions.seal(state,output_epoch=1)
 state=transitions.qualify_generated_media(state,reservation=reservation,resource_id=resource,content_digest=digest,
  specification_digest=reservation.specification_digest,policy_revision=reservation.policy_revision)
 reservation=state.image_reservations[0]
 effect=compile_generated_media(resource,digest,epoch=1,activity=1)
 accepted=transitions.accept_generated_media(state,reservation=reservation,effect=effect)
 assert accepted.active_grants==(effect,) and accepted.sealed
 assert transitions.accept_generated_media(accepted,reservation=reservation,effect=effect) is accepted
 stopped=transitions.stop(state,activity_seq=2,cutoff=0)
 assert transitions.accept_generated_media(stopped,reservation=reservation,effect=effect) is stopped
 dismissed=transitions.dismiss_photo(state,expected_revision=0,cutoff=0)
 assert transitions.accept_generated_media(dismissed,reservation=reservation,effect=effect) is dismissed


import threading
import time
import struct
import zlib
from fastapi.testclient import TestClient
from mira.application.contracts import CandidateRange, EffectProposal, generation_context_data
from mira.bootstrap.direct_provider_app import create_direct_provider_app
from tests.contracts.test_direct_provider_app import arguments
from tests.contracts.test_conversation_first import session,submit,settled
from tests.contracts.test_development_review_composition import SyntheticJevTransport
from mira.domain.story_images import REQUIRED_PIXEL_CHECKS


def png():
 def chunk(tag,data):return struct.pack('!I',len(data))+tag+data+struct.pack('!I',zlib.crc32(tag+data))
 return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',1024,1024,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\x20\x40\x80'*1024)*1024))+chunk(b'IEND',b'')

class Decoder:
 def canonicalize(self,data):
  assert data==png()
  return CanonicalImage(data,1024,1024)

class Images:
 def __init__(self,gate=False,ignore=False):
  self.requests=[];self.arrived=threading.Event();self.release=threading.Event();self.gate=gate;self.ignore=ignore
 async def generate(self,request):
  self.requests.append(request);self.arrived.set()
  while self.gate and not self.release.is_set():
   try:await asyncio.sleep(.002)
   except asyncio.CancelledError:
    if not self.ignore:raise
  return GeneratedImage(png(),'image/png','synthetic','fixture')

class Vision:
 def __init__(self,mode='allow'):
  self.calls=[];self.mode=mode
 async def review(self,artifact,request):
  self.calls.append((artifact,request))
  checks=tuple(PixelCheck(name,'fail' if self.mode=='reject' else 'pass') for name in REQUIRED_PIXEL_CHECKS)
  return MediaReviewObservation(request.request_id,request.specification_digest,
   '0'*64 if self.mode=='wrong_digest' else artifact.content_digest,request.policy_revision,checks,'An empty fictional lighthouse coast.')

class Generation:
 def __init__(self,image=True):self.contexts=[];self.image=image
 async def generate(self,context):
  self.contexts.append(context)
  yield CandidateRange((EffectProposal(EffectKind.SUBTITLE,'I can try a fictional lighthouse illustration.'),),
   'synthetic-image',image_proposal_json=json.dumps(ImageProposal('authored_lighthouse_coast').as_dict()) if self.image else None)


def app_for(images,vision,*,enabled=True,timeout=1,review='allow'):
 generation=Generation();wire=SyntheticJevTransport(output_choice=review)
 factory=lambda _state:StoryImageRuntime(images,vision,Decoder(),StoryImageAdmission('synthetic-only',True,timeout_seconds=timeout))
 app=create_direct_provider_app(**arguments(generation=generation,input_transport=wire,output_transport=wire,
  character_factory=ephemeral_character_factory(),story_image_factory=factory if enabled else None,
  session_turn_limit=4,input_request_limit=4,output_request_limit=4))
 return app,generation,wire


def image_settled(client,path,headers):
 until=time.monotonic()+2
 while time.monotonic()<until:
  state=client.get(path,headers=headers).json()
  if state['story_image']['state'] in ('qualified','presented','failed','held','unavailable','cancelled') and state['sealed']:return state
  time.sleep(.003)
 pytest.fail('image did not settle: '+str(state))


def image_body(effect):
 resource,digest=parse_generated_photo(effect['value'])
 return resource,dict(effect_id=effect['id'],digest=effect['digest'],output_epoch=effect['output_epoch'],activity_seq=effect['activity_seq'],content_digest=digest)


def test_actor_postseal_exact_pixel_asgi_receipt_and_context():
 images=Images(gate=True);vision=Vision();app,generation,wire=app_for(images,vision)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers,text='Please illustrate the fictional lighthouse coast.')
  state=settled(client,path,headers)
  assert images.arrived.wait(1) and state['sealed'] and state['story_image']['state']=='generating'
  assert [e['kind'] for e in state['active_grants']]==['subtitle']
  images.release.set();state=image_settled(client,path,headers)
  assert state['story_image']['state']=='qualified' and state['last_error'] is None
  photo=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=image_body(photo)
  assert len(vision.calls)==1 and vision.calls[0][0].png==png()
  result=client.post(path+'/story-images/'+resource,headers=headers,json=body)
  assert result.status_code==200 and result.content==vision.calls[0][0].png and result.headers['cache-control']=='no-store'
  assert hashlib.sha256(result.content).hexdigest()==body['content_digest']
  assert client.post(path+'/story-images/'+resource,headers={'X-Mira-Session-Token':'wrong'},json=body).status_code==404
  for seq,effect in enumerate(state['active_grants'],1):
   receipt={k:effect[k] for k in ('digest','output_epoch','activity_seq')};receipt.update(effect_id=effect['id'],presentation_seq=seq)
   assert client.post(path+'/receipts',headers=headers,json=receipt).status_code==200
  state=client.get(path,headers=headers).json();assert state['story_image']['state']=='presented' and state['photo_visible']
  generation.image=False;submit(client,path,headers,activity=2,cutoff=2,text='What picture was shown?');settled(client,path,headers)
  facts=generation_context_data(generation.contexts[-1])['story_images']
  assert facts[0]['state']=='presented' and facts[0]['provenance']=='generated_visualization'
  assert facts[0]['observed_description']=='An empty fictional lighthouse coast.'
  assert client.post(path+'/story-images/'+resource,headers=headers,json=body).status_code==409
  output=next(call[0] for call in wire.calls if 'contract' in call[0]['state'])
  assert output['state']['candidate']['image_intent']['specification_digest']==images.requests[0].specification_digest
  assert any(k.endswith(':image_intent') for k in output['questions'])


@pytest.mark.parametrize('fence',['stop','dismiss','close'])
def test_uncooperative_image_cannot_revive_after_fence(fence):
 images=Images(gate=True,ignore=True);vision=Vision();app,generation,_=app_for(images,vision)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);settled(client,path,headers)
  assert images.arrived.wait(1)
  if fence=='stop':assert client.post(path+'/stop',headers=headers,json={'activity_seq':2,'presentation_cutoff':0}).status_code==200
  elif fence=='new_input':generation.image=False;submit(client,path,headers,activity=2);settled(client,path,headers)
  elif fence=='dismiss':assert client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':0,'target':'all_photos'}).status_code==200
  else:assert client.delete(path,headers=headers).status_code==204
  images.release.set();time.sleep(.03)
  if fence!='close':
   state=client.get(path,headers=headers).json();assert not any(e['kind']=='media' for e in state['active_grants'])
  assert vision.calls==[]


@pytest.mark.parametrize('mode',['reject','wrong_digest'])
def test_bad_pixel_review_holds_only_image(mode):
 images=Images();vision=Vision(mode);app,_,_=app_for(images,vision)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);state=image_settled(client,path,headers)
  assert state['last_error'] is None and state['story_image']['state']=='failed'
  assert [e['kind'] for e in state['active_grants']]==['subtitle']


@pytest.mark.parametrize('enabled,review',[(False,'allow'),(True,'reject'),(True,'unknown')])
def test_absent_or_unapproved_images_never_call_provider_or_fail_chat(enabled,review):
 images=Images();app,_,_=app_for(images,Vision(),enabled=enabled,review=review)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);state=settled(client,path,headers)
  assert state['last_error'] is None and not images.requests
  assert [e['kind'] for e in state['active_grants']]==['subtitle']


def test_new_input_preserves_generating_image_and_context():
 images=Images(gate=True);app,generation,_=app_for(images,Vision())
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);settled(client,path,headers);assert images.arrived.wait(1)
  generation.image=False;submit(client,path,headers,activity=2);state=settled(client,path,headers)
  assert state['story_image']['state']=='generating'
  assert generation.contexts[-1].story_images[0].state=='generating'
  images.release.set()


def test_resource_bytes_cannot_drift_after_qualification():
 images=Images();app,_,_=app_for(images,Vision())
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);state=image_settled(client,path,headers)
  photo=next(e for e in state['active_grants'] if e['kind']=='media');resource,body=image_body(photo)
  actor=app.state.container.sessions.get(state['session_id'],headers['X-Mira-Session-Token'])
  store=actor._story_images
  store._artifacts[resource]=replace(store._artifacts[resource],png=png()+b'changed')
  assert client.post(path+'/story-images/'+resource,headers=headers,json=body).status_code==409


def test_late_vision_cannot_survive_dismissal_and_receipts_do_not_fabricate_display():
 class GatedVision(Vision):
  def __init__(self):super().__init__();self.arrived=threading.Event();self.release=threading.Event()
  async def review(self,artifact,request):
   self.arrived.set()
   while not self.release.is_set():
    try:await asyncio.sleep(.002)
    except asyncio.CancelledError:pass
   return await super().review(artifact,request)
 vision=GatedVision();app,_,_=app_for(Images(),vision)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);settled(client,path,headers);assert vision.arrived.wait(1)
  assert client.post(path+'/photo-dismissals',headers=headers,json={'request_id':str(uuid4()),'expected_revision':0,'presentation_cutoff':0,'target':'all_photos'}).status_code==200
  vision.release.set();time.sleep(.03)
  state=client.get(path,headers=headers).json()
  assert state['story_image']['state']=='cancelled' and state['presented_effects']==[]
  assert [e['kind'] for e in state['active_grants']]==['subtitle']


def test_image_timeout_is_finite_even_when_provider_ignores_cancel():
 images=Images(gate=True,ignore=True);app,_,_=app_for(images,Vision(),timeout=.025)
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);state=image_settled(client,path,headers)
  assert state['story_image']['state']=='failed' and state['story_image']['failure_code']=='timeout'
  assert state['last_error'] is None and [e['kind'] for e in state['active_grants']]==['subtitle']
  images.release.set();time.sleep(.03)
  assert client.get(path,headers=headers).json()['story_image']['state']=='failed'


def test_default_unavailable_image_proposal_parser_preserves_valid_text():
 from mira.adapters.generation.codex_support.character_payload import parse_image_character_candidate
 from mira.adapters.generation.codex_support.types import CodexLimits
 from mira.application.contracts import GenerationContext
 for proposal in [ImageProposal('authored_lighthouse_coast').as_dict(),{'prompt':'private arbitrary detail'},'bad']:
  effects,_,_,raw=parse_image_character_candidate([json.dumps({'effects':[{'kind':'subtitle','value':'Useful chat'}],
   'image_proposal':proposal})],CodexLimits(),GenerationContext('hello',('hello',),(),1),speech_enabled=False)
  assert effects[0].value=='Useful chat' and raw is not None


def test_generated_picture_never_claims_fixed_authored_photo_is_visible():
 from mira.application.authored_visual_events import visual_facts
 from mira.application.contracts import GenerationContext
 effect=compile_generated_media(str(uuid4()),'a'*64,epoch=1,activity=1)
 context=GenerationContext('picture',('picture',),(effect,),1,photo_visible=True)
 assert visual_facts(context)['trip_photo']['visible'] is False


def test_unqualified_reservation_cannot_admit_arbitrary_pixels():
 state=transitions.begin_input(SessionState('s','c'),activity_seq=1,cutoff=0,request_id='turn',text='scene')
 reservation=ImageReservation('image','turn',1,1,0,'b'*64,'c'*64,'image-policy-v1',session_id='s')
 state=transitions.reserve_generated_media(state,reservation)
 effect=compile_generated_media(str(uuid4()),'d'*64,epoch=1,activity=1)
 assert transitions.accept_generated_media(state,reservation=reservation,effect=effect) is state


@pytest.mark.parametrize('change', ['request','spec','policy','missing','extra','unknown'])
def test_every_pixel_binding_and_required_check_is_enforced(change):
 class Changed(Vision):
  async def review(self,artifact,request):
   result=await super().review(artifact,request)
   if change=='request':return replace(result,request_id='wrong')
   if change=='spec':return replace(result,specification_digest='0'*64)
   if change=='policy':return replace(result,policy_revision='old')
   if change=='missing':return replace(result,checks=result.checks[:-1])
   if change=='extra':return replace(result,checks=result.checks+(PixelCheck('other','pass'),))
   return replace(result,checks=(replace(result.checks[0],result='unassessable'),)+result.checks[1:])
 app,_,_=app_for(Images(),Changed())
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);state=image_settled(client,path,headers)
  assert state['story_image']['state']=='failed' and state['story_image']['failure_code']=='review'
  assert [e['kind'] for e in state['active_grants']]==['subtitle'] and state['last_error'] is None


def test_budget_reserved_before_calls_and_private_input_excluded():
 images=Images();app,generation,_=app_for(images,Vision())
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers,text='Synthetic PRIVATE_USER_SENTINEL. Please draw the lighthouse.')
  state=image_settled(client,path,headers)
  actor=app.state.container.sessions.get(state['session_id'],headers['X-Mira-Session-Token'])
  assert actor._story_images.attempts==1 and not actor._story_images.reserved_bytes
  request=images.requests[0]
  assert 'PRIVATE_USER_SENTINEL' not in request.specification and request.allowed_resource_ids==()
  assert request.specification_digest==hashlib.sha256(request.specification.encode()).hexdigest()
  assert not generation.contexts[0].story_images
  assert state['story_image']['state']=='qualified' and state['presented_effects']==[]
  resource,body=image_body(state['active_grants'][-1])
  wrong={**body,'content_digest':'0'*64}
  assert client.post(path+'/story-images/'+resource,headers=headers,json=wrong).status_code==409


def test_history_pending_input_revokes_reply_but_keeps_image():
 images=Images(gate=True);app,_,_=app_for(images,Vision())
 with TestClient(app) as client:
  path,headers=session(client);submit(client,path,headers);settled(client,path,headers);assert images.arrived.wait(1)
  response=client.post(path+'/inputs',headers=headers,json={'request_id':str(uuid4()),'activity_seq':2,
   'presentation_cutoff':1,'text':'new topic'})
  assert response.status_code==409
  state=client.get(path,headers=headers).json()
  assert state['story_image']['state']=='generating' and state['active_grants']==[]
  images.release.set()


def test_image_cue_bypasses_caption_boundary_calls():
 from mira.application.semantic_chunking import make_request
 from mira.application.contracts import GenerationContext
 candidate=CandidateRange((EffectProposal(EffectKind.SUBTITLE,
  'First complete sentence. Second complete sentence. Third complete sentence.'),),'image-cue',
  image_proposal_json=json.dumps(ImageProposal('authored_lighthouse_coast').as_dict()))
 assert make_request(GenerationContext('draw',('draw',),(),1),candidate) is None


def test_author_instructions_explain_enabled_bounded_image_proposals():
 from mira.adapters.generation.codex_support.payload import author_instructions
 ordinary=author_instructions(speech_enabled=False,memory_enabled=False)
 enabled=author_instructions(speech_enabled=False,memory_enabled=False,story_images_enabled=True)
 assert 'image_proposal' in enabled and 'generated_visualization' in enabled
 assert enabled.startswith(ordinary) and 'image_proposal' not in ordinary
