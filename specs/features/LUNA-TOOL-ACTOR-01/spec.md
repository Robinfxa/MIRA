# LTA-01: application-owned tool execution and real result continuation

Base: frozen0221 whitelist capture SHA256 22a4f2e26a113fdc5ed88419596a2444a83261e2747cf25d632cdb87145fb686. Owner: actor slice; formal port and bootstrap belong to integration, fiction compiler and JEV image validation belong to image slice.

### LTA01-001 Exact results
Given one advertised fixed-image call, when PHOTO-03 local fixed-asset admission grants it, only an exact accepted presentation receipt may return shown. Generated-image attempts retain their optional semantic review. An absent ACK is pending. Already visible matching content can reuse its existing receipt without rendering/reviewing twice. Readiness, generation, qualification, grant, receipt and visibility remain different facts.

### LTA01-002 Bounded execution
Given an untrusted call, reject unknown names, duplicate keys, unexpected fields and invalid argument types before side effects. Advertise only presently admitted capabilities. Return held/failed/pending/unavailable truthfully. One operation and at most one continuation; only subtitle/speech is allowed from continuation. Mixed controls/proposals are invalid_response; a real earlier receipt and current visible image survive continuation failure. Ordinary dialogue still follows held optional events. Ordinary first candidates preserve existing reviewed pose/scene/story/affect. Existing explicit subtitle chunking is invoked once on the complete tool-path final candidate.

### LTA01-003 Lifecycle
Given a provider or renderer wait, no transition lock is held. Stop, new input, dismissal and Close synchronously fence the handle and cancel continuation. A late previously valid receipt may enter history under the existing fences without reviving execution. Long images may return pending while the existing bounded job continues; completion never adds a third generation call.

## Quality and resources
New tests/contracts/test_luna_tool_actor.py belongs uniquely to providers through tests/quality.toml tests/contracts/test_*.py. Consumers: SessionActor, optional JEV, fixed-photo grants/progress, StoryImageRuntime, exact receipt reducer and direct tool backend. No new package, network, auth, environment or database read. RED/GREEN and affected synthetic checks only; real provider/device display are not run. Evidence outside source tree.

Integration seam: ResponseContractProducer adds optional_image_only=False. Only explicit conversation-first stage review can admit empty effects with exact ImageIntent and valid story, no sibling proposals or caption chunk. Speech and ordinary producer defaults remain closed. JEV independently reconstructs the contract using its existing image-question revision before performing actual output review.
