# Direct provider application composition

The final product route is direct provider HTTP, with subscription OAuth and official API-key routes explicitly distinct. The native Codex adapter remains an optional development tool. This slice does not perform a real login or provider call; credentials and user transmission/billing consent are supplied at the outer entrypoint.

### DIRECTPROVIDERENTRY-001 Explicit route and billing boundary
- Subscription and API routes require a selected model, injected GenerationBackend and explicit transmission consent. API additionally requires explicit API-billing acknowledgement. No route fallback or native executable/admission is consulted.
### DIRECTPROVIDERENTRY-002 Existing review and lifecycle
- Real JEV input/output ports, Actor, receipt/Stop and optional bounded Google voice remain behind the same application contracts. Injected synthetic providers can exercise the app without a Codex installation.
### DIRECTPROVIDERENTRY-003 Memory consent remains separate
- Existing memory recording consent is not consent to send stored records to a new direct provider route; explicit new transmission acknowledgement and local operator pairing are required before that optional path can be composed. Default does not read memory.
