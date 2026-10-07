# Direct provider memory, explicit and optional

Default startup never reads local memory. Initialize and populate your own private
scope using the existing local memory CLI; this feature does not record chats or
extract memories automatically. Keep the database and scope configuration outside
the source checkout. See LOCAL_MEMORY.md for exact scope-file format and commands.

Add these options to the existing explicit `tools/live_provider.py check/serve`
command only when you intend to share selected stored statements with the chosen
OpenAI route:

```
--memory-db /absolute/private/memory.sqlite3
--memory-scope-config /absolute/private/scopes.json
--memory-scope YOUR_LOCAL_ALIAS
--authorize-memory-to-selected-provider
--create-local-operator-pairing
```

`--authorize-memory-to-selected-provider-and-jev` remains a compatibility alias.
Default `luna_tools` mode uses no JEV credentials, runtime reviews or memory
transmission. Only an explicit `--action-review-mode legacy_jev` selects the old
JEV route and adds it to the disclosed recipients. Neither flag enables automatic
recording or authorizes Google-derived speech.

`check` validates declarations and recipient names; it creates no code, opens no
database and makes no model request. `serve` creates an expiring, one-use pairing
code in a private local file after the local frontend builds. The console prints
only that file's path. Enter its code in the local page, never in chat or a URL.
The boundary protects the configured local scope from unpaired browser clients;
it does not protect against someone using your OS account or authenticated browser.

The optional `--authorize-local-memory-management` separately enables the paired
manual save/correct/soft-forget/restore panel. Each write requires confirmation.
Local recording permission and provider transmission permission are different.

## With speech

Voice already requires `--voice`, an explicit ADC path and
`--authorize-google-voice-data-and-spend`. When memory is also enabled add:

```
--authorize-memory-derived-speech-to-google
```

This acknowledges that approved generated speech may contain recalled details and
will be sent to Google Cloud TTS. STT consumes microphone frames, not the database.
The page discloses the selected OpenAI recipient and this TTS possibility
(and JEV only in explicit legacy mode)
before pairing. No microphone starts before your gesture/browser permission.

Correction or soft-forget changes the bound scope revision. Pending generation,
review and later speech dispatch are checked against it; subsequent audio delivery
stops when drift is detected. Stop is never blocked waiting for the memory reader.
Already transmitted provider text and already played sound cannot be retracted.
Revoking pairing closes the local session, memory reader/manager and voice bundle.

Current validation uses synthetic SQLite records, synthetic direct HTTP streams,
synthetic PCM and, only for legacy compatibility tests, synthetic JEV responses. It proves software wiring and bounds,
not real provider quality, human hearing, automatic memory learning or completeM06.
