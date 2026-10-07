# Direct provider startup diagnostics

## Scope and ownership

Base: immutable `mira-conversation-first-capture-20261005T0550Z` source snapshot.
This isolated slice changes only the direct launcher and its existing provider-owned
contract tests; the integration owner merges its shared launcher surface. Consumers
are direct launch checks and serve startup. Tests use temporary synthetic env/ADC
files and mocked resource constructors. No actual credential contents, authentication,
SDK discovery, provider requests, or user-device validation are part of this work.

### DIRECTSTARTUPDIAGNOSTICS-001 Actionable safe configuration failures

Given a voice name placed in TTS_LOCATION, when check or serve loads configuration,
then startup fails at config_validation before ADC metadata or resources and reports
the allowlisted field TTS_LOCATION with the required fixed location global. Other
known invalid configuration fields are allowlisted and bounded. Unknown field names,
values, paths, exception text, headers, and credential contents are never returned.

### DIRECTSTARTUPDIAGNOSTICS-002 Metadata failure stage

Given a missing or unsafe explicit env or ADC file, when check validates its metadata,
then startup identifies env_file_metadata or adc_file_metadata without reading the
ADC contents, allocating provider resources, or printing any selected path.

Full/release, live provider authorization, actual SDK readiness, microphone, playback,
and Mac acceptance remain outside this isolated synthetic verification.
