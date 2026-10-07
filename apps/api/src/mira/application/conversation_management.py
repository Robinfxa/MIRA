"""One paired fixed-scope archive owner and per-Actor recording bindings."""
import asyncio
from mira.application.actor_conversation import SessionConversationBinding
from mira.application.conversation_archive import ConversationArchiveError


class ConversationRuntime:
    def __init__(self, archive, *, management=False, recall_session_id=None,
                 recall_authorized=False, google_authorized=False, speech_enabled=False,
                 recipients='selected generation provider and TypeSafe/JEV'):
        self.archive=archive
        self.management=management
        self.recall_session_id=recall_session_id
        self.recall_authorized=recall_authorized
        self.google_authorized=google_authorized
        self.speech_enabled=speech_enabled
        self.recipients=recipients
        self.current=None
        self.current_session_id=None
        self.started=False
        self.revoked=False
        self.available=True
        self._lock=asyncio.Lock()
        self._closed=False

    def create(self,state):
        self.started=True
        self.current_session_id=state.session_id
        self.current=SessionConversationBinding(self,authorize_transcript_persistence=True,
            recall_session_id=self.recall_session_id,
            authorize_recall_to_provider_and_jev=self.recall_authorized,
            speech_enabled=self.speech_enabled,authorize_recalled_speech_to_google=self.google_authorized)
        if self.revoked: self.current.revoke()
        return self.current

    def _guard(self):
        if self.revoked or self._closed:
            raise ConversationArchiveError('conversation_revoked')
        if not self.available:
            raise OSError('conversation_unavailable')

    async def _call(self,name,*args,**kwargs):
        self._guard()
        async with self._lock:
            self._guard()
            result=await getattr(self.archive,name)(*args,**kwargs)
            if name not in ('capture','management_apply'): self._guard()
            return result

    async def capture(self,*args): return await self._call('capture',*args)
    async def load_session(self,*args): return await self._call('load_session',*args)
    async def session_revision(self,*args): return await self._call('session_revision',*args)
    async def wait_idle(self): return await self.archive.wait_idle()

    def status(self):
        status=('revoked_existing_records_retained' if self.revoked else
            'unavailable' if not self.available else
            self.current.persistence_status if self.current is not None else 'enabled_no_committed_records')
        return dict(enabled=True,persistence_status=status,management_enabled=self.management and not self.revoked,
            recall_session_id=self.recall_session_id,current_session_id=self.current_session_id,
            selection_locked=self.started or self.revoked,recipients=self.recipients,
            speech_enabled=self.speech_enabled,recall_authorized=self.recall_authorized,
            google_authorized=self.google_authorized)

    async def _settle(self):
        if self.current is not None:
            await self.current.flush(wait_for_retry=True)
        self._guard()

    async def list_sessions(self,cursor=None):
        await self._settle()
        return await self._call('list_sessions',cursor=cursor)

    async def page(self,session_id,cursor=None):
        await self._settle()
        return await self._call('management_page',session_id,cursor=cursor)

    async def select(self,session_id,*,recall_consent,google_consent):
        if self.started:
            raise ConversationArchiveError('conversation_selection_locked')
        if self.revoked or self._closed:
            raise ConversationArchiveError('conversation_revoked')
        if google_consent and not self.speech_enabled:
            raise ConversationArchiveError('conversation_google_consent_invalid')
        if session_id is not None:
            if recall_consent is not True or (self.speech_enabled and google_consent is not True):
                raise ConversationArchiveError('conversation_recall_consent_required')
            snapshot=await self.load_session(session_id)
            if self.started or self.revoked or self._closed:
                raise ConversationArchiveError('conversation_selection_locked')
            if not snapshot.records:
                raise ConversationArchiveError('conversation_session_unavailable')
        elif recall_consent or google_consent:
            raise ConversationArchiveError('conversation_selection_invalid')
        self.recall_session_id=session_id
        self.recall_authorized=recall_consent
        self.google_authorized=google_consent
        return self.status()

    async def apply(self,session_id,command):
        if not self.management:
            raise ConversationArchiveError('conversation_management_not_authorized')
        await self._settle()
        return await self._call('management_apply',session_id,command)

    def revoke(self):
        self.revoked=True
        if self.current is not None: self.current.revoke()

    async def aclose(self):
        if self._closed:return
        self.revoke()
        self._closed=True
        await self.archive.aclose()
