"""Inert direct-entry composition; called only behind verified operator pairing."""
from mira.config.conversation import validate_conversation_options
from mira.adapters.memory.async_conversation import AsyncConversationArchive
from mira.application.conversation_management import ConversationRuntime


def conversation_factory(options,*,speech_enabled=False,recipients):
    validate_conversation_options(options,speech_enabled=speech_enabled)
    async def open_runtime():
        validate_conversation_options(options,speech_enabled=speech_enabled)
        archive=AsyncConversationArchive(options.database,fixed_scope=options.scope,
            enabled=True,authorize_transcript_persistence=True)
        runtime=ConversationRuntime(archive,management=options.authorize_management,
            recall_session_id=options.recall_session_id,
            recall_authorized=options.authorize_recall_to_provider_and_jev,
            google_authorized=options.authorize_recalled_speech_to_google,
            speech_enabled=speech_enabled,recipients=recipients)
        try:
            await archive.open(pairing_confirmed=True)
            if options.recall_session_id is not None:
                snapshot=await archive.load_session(options.recall_session_id)
                if not snapshot.records:
                    from mira.application.conversation_archive import ConversationArchiveError
                    raise ConversationArchiveError('conversation_session_unavailable')
        except (OSError,TimeoutError):
            # Recording failure stays visible and does not prevent ordinary chat.
            runtime.available=False
        except BaseException:
            await archive.aclose()
            raise
        return runtime
    return open_runtime
