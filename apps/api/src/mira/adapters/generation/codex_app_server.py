"""Default-OFF, category-isolated Codex subscription generation.

The composition root supplies trusted paths, process environment, admission and budget.
No credentials/environment are discovered. This adapter grants no review or presentation
permission. All messages, including async delivery, remain untrusted candidate content.
"""
from __future__ import annotations

import asyncio

from mira.application.response_preference import generation_speech_enabled
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress

from mira.application.contracts import CandidateRange, GenerationContext

from .codex_support.payload import build_prompt
from .codex_support.process import open_stdio
from .codex_support.protocol import Session
from .codex_support.types import (
    CodexGenerationError,
    CodexLimits,
    CodexRuntime,
    CodexTransport,
)

__all__ = ['CodexAppServerGenerationBackend', 'CodexGenerationError', 'CodexLimits', 'CodexRuntime']
TransportFactory = Callable[[CodexRuntime, CodexLimits], Awaitable[CodexTransport]]


class CodexAppServerGenerationBackend:
    def __init__(self, *, runtime: CodexRuntime, admitted: bool = False,
                 request_limit: int = 0, limits: CodexLimits | None = None,
                 transport_factory: TransportFactory | None = None,
                 speech_enabled: bool = True) -> None:
        if (type(runtime) is not CodexRuntime or type(admitted) is not bool
                or type(speech_enabled) is not bool):
            raise ValueError('codex_admission_invalid')
        if type(request_limit) is not int or not 0 <= request_limit <= 100:
            raise ValueError('codex_request_limit_invalid')
        if limits is not None and type(limits) is not CodexLimits:
            raise ValueError('codex_limits_invalid')
        self._runtime = runtime
        self._admitted = admitted
        self._remaining = request_limit
        self._limits = limits or CodexLimits()
        self._factory = transport_factory or open_stdio
        self._speech_enabled = speech_enabled

    async def generate(self, context: GenerationContext) -> AsyncIterator[CandidateRange]:
        if not self._admitted:
            raise CodexGenerationError('codex_not_admitted')
        if not self._remaining:
            raise CodexGenerationError('codex_budget_exhausted')
        speech_enabled = generation_speech_enabled(context, self._speech_enabled)
        prompt = build_prompt(context, self._limits, speech_enabled=speech_enabled)
        self._remaining -= 1  # Reserve before the first await; failures consume admission.
        transport = None
        session = None
        successful = False
        effects = None
        try:
            async with asyncio.timeout(self._limits.startup_seconds):
                transport = await self._factory(self._runtime, self._limits)
                session = Session(transport, self._runtime, self._limits,
                                  speech_enabled=speech_enabled,
                                  memory_enabled=context.memory_packet is not None)
                await session.start()
            async with asyncio.timeout(self._limits.turn_seconds):
                effects = await session.run(prompt)
            successful = True
        except TimeoutError:
            raise CodexGenerationError('codex_timeout') from None
        except asyncio.CancelledError:
            raise
        except CodexGenerationError:
            raise
        except Exception:
            raise CodexGenerationError('codex_transport_failed') from None
        finally:
            if transport is not None:
                async def cleanup():
                    if session is not None and not successful:
                        with suppress(Exception):
                            async with asyncio.timeout(self._limits.shutdown_seconds):
                                await session.interrupt()
                    await transport.close()
                task = asyncio.create_task(cleanup())
                try:
                    # The real transport additionally bounds TERM/KILL/wait operations.
                    async with asyncio.timeout(4 * self._limits.shutdown_seconds):
                        await asyncio.shield(task)
                except asyncio.CancelledError:
                    with suppress(Exception):
                        async with asyncio.timeout(4 * self._limits.shutdown_seconds):
                            await asyncio.shield(task)
                    raise
                except Exception:
                    task.cancel()
                    with suppress(Exception, asyncio.CancelledError):
                        await task
                    if successful:
                        raise CodexGenerationError('codex_process_cleanup_failed') from None
                finally:
                    if session is not None:
                        session.discard()
        # No yield is reachable after cancellation, failure, malformed output or failed cleanup.
        assert successful and effects is not None
        yield CandidateRange(effects, f'codex-origin:{uuid.uuid4().hex}')
