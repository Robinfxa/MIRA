# Finite chapter application integration

Base: frozen 0542, plus verified IMG-03, WP12 clothing and closed wardrobe diagnostics. This integration owns SessionActor, HTTP DTOs, generated contracts and readiness/bootstrap. WP13 owns typed chapter reduction; XIAHE-PRESENTATION owns code-native screen composition.

## Shared-state contract

SessionView.chapter_projection is a bounded read-only projection of the application's chapter state. It includes only fixed schema/source hashes, closed stage/transition labels, fictional role, exact current offer identity and revision. Canon text, memory scope and provider/user data are not copied to this DTO. Clients cannot submit a chapter projection as authority.

Explicit accept/decline uses InputRequest.chapter_choice and the same authenticated input, history-cutoff, cancellation and idempotency path. Before changing the input, the Actor checks the current exact invitation; unknown/changed choices do not consume a turn. An accepted button produces one local typed candidate without opening a model/tool turn or reading optional recall packets. Natural-language choices retain the normal model-proposal path. Both require the same finite transition rules and actual presentation receipt.

Ordinary dialogue is published independently. Chapter plans use closed deterministic conditions, not a second whole-dialogue semantic vote. Unrelated optional controls cannot inherit chapter authority. Room, outfit and chapter presentation remain separate state channels. A same-epoch actual subtitle receipt may reconcile a narrated beat; Stop/new input cannot create a new action from late output.

The real show_photo tool may reuse a previously shown, currently visible fixed photograph. The chapter records a reference to the original exact receipt, never a duplicate media effect, new exposure receipt or gifted-photo claim. Checkpoint I/O occurs outside the Actor lock; cancellation still fences the provider continuation.

## Resources and installation

The default code renderer's existing source pins and fixed photo must remain verified. Chapter capabilities also attest the presenter, executor, controller, protocol, main entry, index and CSS. The wheel includes these public source-evidence files as package data; they are not mounted as source-code HTTP endpoints. Missing chapter files make only these chapter capabilities unavailable; the existing fixed photo remains available.

## Verification

Focused contracts cover public schema/aliases, no client-supplied state authority, local disabled-choice rejection before input consumption, exact source resources and installed resource declarations. Independent compiled-controller/ASGI checks cover the complete chapter, early preview reuse, refusal/reopening, Stop during transfer, stale input/receipt and the original model budget. A full fixed-source release and restore gate is required before a deliverable is READY. Actual browser/device/provider acceptance is separate; offline raster compositions are not browser screenshots.
