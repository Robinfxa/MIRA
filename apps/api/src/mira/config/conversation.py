"""Explicit conversation persistence configuration; metadata checks only."""
from dataclasses import dataclass, field
from pathlib import Path
import os
import stat

from mira.config.loader import ConfigurationError
from mira.config.memory_scope import _private_existing_file, _read_scope
from mira.domain.memory import MemoryScope


@dataclass(frozen=True, slots=True)
class ConversationArchiveOptions:
    database: Path = field(repr=False)
    scope: MemoryScope = field(repr=False)
    checkout_root: Path = field(repr=False)
    excluded_databases: tuple[Path, ...] = field(default=(), repr=False)
    authorize_persistence: bool = False
    authorize_management: bool = False
    recall_session_id: str | None = None
    authorize_recall_to_provider_and_jev: bool = False
    authorize_recalled_speech_to_google: bool = False


def validate_conversation_options(options, *, speech_enabled=False):
    if type(options) is not ConversationArchiveOptions or type(options.scope) is not MemoryScope:
        raise ConfigurationError('conversation_options_invalid')
    if any(type(v) is not bool for v in (options.authorize_persistence, options.authorize_management,
            options.authorize_recall_to_provider_and_jev, options.authorize_recalled_speech_to_google)):
        raise ConfigurationError('conversation_consent_invalid')
    if not options.authorize_persistence:
        raise ConfigurationError('conversation_persistence_consent_required')
    if options.recall_session_id is not None:
        value=options.recall_session_id
        if type(value) is not str or not 1 <= len(value) <= 128 or any(c.isspace() or ord(c)<33 or ord(c)==127 for c in value):
            raise ConfigurationError('conversation_session_invalid')
        if not options.authorize_recall_to_provider_and_jev:
            raise ConfigurationError('conversation_recall_consent_required')
        if speech_enabled and not options.authorize_recalled_speech_to_google:
            raise ConfigurationError('conversation_google_consent_required')
    if options.authorize_recalled_speech_to_google and (not speech_enabled or not options.authorize_recall_to_provider_and_jev):
        raise ConfigurationError('conversation_google_consent_invalid')
    path=options.database
    if not isinstance(path,Path) or not path.is_absolute() or '..' in path.parts:
        raise ConfigurationError('conversation_database_path_invalid')
    try:
        root=options.checkout_root.resolve()
        if path == root or root in path.parents or path.resolve() != path:
            raise ConfigurationError('conversation_database_path_invalid')
        # Existing and new paths use the same owner-private file/parent policy.
        if path.exists():
            _private_existing_file(path,label='conversation_database',checkout_root=root)
        else:
            parent=path.parent
            info=parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode)&0o077):
                raise ConfigurationError('conversation_database_not_private')
            current=Path(path.anchor)
            for part in parent.parts[1:]:
                current/=part
                item=current.lstat()
                if (stat.S_ISLNK(item.st_mode) or not stat.S_ISDIR(item.st_mode)
                        or item.st_uid not in {0,os.geteuid()}
                        or (stat.S_IMODE(item.st_mode)&0o022 and not item.st_mode&stat.S_ISVTX)):
                    raise ConfigurationError('conversation_database_not_private')
        for other in options.excluded_databases:
            if path.resolve() == other.expanduser().resolve() or (path.exists() and other.exists() and os.path.samefile(path,other)):
                raise ConfigurationError('conversation_database_must_be_dedicated')
    except ConfigurationError:
        raise
    except (OSError,RuntimeError):
        raise ConfigurationError('conversation_database_unavailable') from None
    return options


def load_conversation_options(*, database, scope_config, scope_alias, checkout_root,
        authorize_persistence=False, authorize_management=False, recall_session_id=None,
        authorize_recall_to_provider_and_jev=False, authorize_recalled_speech_to_google=False,
        speech_enabled=False, excluded_databases=()):
    if authorize_persistence is not True:
        raise ConfigurationError('conversation_persistence_consent_required')
    config=_private_existing_file(scope_config,label='scope_config',checkout_root=checkout_root)
    scope=_read_scope(config,scope_alias)
    return validate_conversation_options(ConversationArchiveOptions(database,scope,checkout_root,
        tuple(excluded_databases),authorize_persistence,authorize_management,recall_session_id,
        authorize_recall_to_provider_and_jev,authorize_recalled_speech_to_google),speech_enabled=speech_enabled)
