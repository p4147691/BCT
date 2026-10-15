# PR3-c: strict internal Native Host ingress contract

Base main: 02d52ea5b2bfa1a3c78631e658d996caad713828. This is **not** a Chrome/Native Host connection, HTTP/MCP listener, nor a production identity authority.

Future host supplies a UTF-8 JSON **bytes** frame to in-process ingress. Max 8192 bytes; no duplicate/unknown/missing top-level keys; version 1; approved operation allowlist; exact request_id, origin, audience, credential, session, node, attachment and integer generation. Arguments must have the exact keys for completion_report, result_get, delivery_receipt_get or recipient_ack. Invalid encodings, duplicate keys, non-finite values, unknown operations and unexpected fields fail closed. Never include credentials or input bytes in errors.

Ingress calls PR3-b `call` after parsing. PR3-b owns grant scope, revocation, expiry, one-shot replay and invocation of PR3-a. PR3-a/PR1/PR2 own RESULT provenance, immutable outbox, send state, epoch/lease, recipient and ACK fencing. No call to existing operational MCP Bearer or Runtime Monitor.

Fake credentials may only be issued through explicitly bound test fixture issuer. Fake recipient_proof remains untrusted mock data, **not** authenticated browser command execution evidence. After SEND_STARTED and ambiguous delivery, Core UNKNOWN must not auto-retry.

Tests can assert envelope-to-adapter routing, malformed/oversize/wrong scope and authorization fence, retry/replay and isolated SQLite. No real Host process, Chrome extension, registry, production issuance or live Core is created. Real Host E2E needs secure Host/Core peer authentication, bounded key provisioning, authentic extension identity/Origin binding, verified browser completion, recipient processing/ACK evidence, and an explicitly authorized isolated Chrome profile with cleanup.
