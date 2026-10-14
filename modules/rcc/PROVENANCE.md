# RCC baseline provenance

Recovered on 2026-10-12 from the currently running RCC installation without
semantic, formatting, or line-ending changes.

- Live extension source: `D:\ACT\relay\extension-live`
- Live native-host source: `D:\ACT\relay\native-host\RelayNativeHostV2.cs`
- Live native-host manifest: `D:\ACT\relay\native-host\com.ai_workspace_relay.host.v2.json`
- Previous canonical repository: `p4147691/AI-CODE-TEAM`
- Previous canonical `main`: `b0148ff1530db6d71f0c665c816c95fc575ff3e2`
- Provenance finding: the live extension contained accepted functionality that
  was not byte-identical to the previous canonical repository. BCT therefore
  preserves the live bytes as its baseline instead of overwriting the working
  installation with older source.
- Native-host executable is deliberately not committed. BCT rebuilds it from the tracked C# source
  and installs it at `D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe`; the manifest keeps the
  existing host name and exact Chrome extension origin.

The recovered ACT paths above document where the byte baseline came from. They are provenance, not
the BCT installation contract. The extension path cutover is separate because an unpacked Chrome
extension without a manifest key derives its ID from its path; BCT must migrate its local state before
changing that path.

## BCT installed identity

The baseline hash table below remains the recovery evidence. The BCT installation intentionally adds
one manifest public key after recovery so the installed extension ID is independent of its directory:

- installed path: `D:\ChromeExtensions\RCC\extension`;
- fixed extension ID: `ocbidbaplechjjdacmokhnfbdmgjkphf`;
- legacy path-derived ID during the bounded cutover only: `bhlcnmbodlhbephppahojbigleklpmhj`.

The migration transition temporarily accepted both IDs while the old instance was inspected.  It did
not copy pending sends or re-run an old browser operation.  After the legacy extension was disabled
and the new exact instance passed state and preserved-tab acceptance, the steady-state Native Host
contract was reduced to the BCT ID only.

## BCT RCC 1.0.1 release payload

Issue #57 adds bounded network-versus-DOM failure evidence without changing submission, duplicate,
pending, or result-ack semantics. The exact payload hashes approved for the 1.0.1 deployment are:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `41415bfbfd91a709a40ba261bd5cd6310964ec67ba33ee4d3a1be14b740e5397` |
| `extension/content.js` | `07884b56191e52fddd00bde2b39ab690e63ec4eeac1854410b8aab2f4cc6f60a` |
| `extension/manifest.json` | `86124e21fd9ddb70a51e61ffa231f27f1529cdf2784eeefd765f7324347d62c3` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |

## BCT RCC 1.0.4 integrated create-and-send candidate

Issue #66 removes the fixed sequential network-signal wait by accepting the
first exact proof from either the observed conversation request or the exact
new user turn. A single BCT `create-and-send` operation now creates the target,
submits once with deterministic child operation IDs, waits read-only for the
persisted assistant result, and returns the conversation and reply. The
receipt records timestamp-only composer stages without storing prompt text.
An UNKNOWN parent can be released only by `reconcile-create-and-send` after an
exact persisted child receipt proves the derived create/send identity; it is
never resent.

Candidate extension payload SHA-256 for 1.0.4:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `486c61e16bbb4bf3aa7df15d1dfa44099f960b8e2ce8a78e6f64a0e750c1f080` |
| `extension/content.js` | `7edb4d4c55ab192e99cc5f5ef4d076a2078bb38246c2fe3304c95ae9c2f9a8b1` |
| `extension/manifest.json` | `d72baf788e792463e96b434b310a3b2e4a1b8d3591831e2cf77df18fb8972b8b` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |

## Exact imported SHA-256 values

| File | SHA-256 |
| --- | --- |
| `extension/act_bridge.js` | `0194c8b1c25676cc7c87ba433f7d72c8e272910cac2c9d36cbc00784303b0a7f` |
| `extension/act_command_bridge.js` | `6e4ff7541a34dabe0d81c2b5815e99ab068b7a76b6a0032c04bd60ff477d8ee7` |
| `extension/act_content.js` | `b5e726d337fb0e2f46481c62c1fa07dc856c7b21c462735d72a61b0a1e643011` |
| `extension/activity_bridge.js` | `850f740bb9142356c228a57ebc65adc26757a69ac9296fd6a90a815c7a04585e` |
| `extension/background_loader.js` | `21ddf802908a427dd2338a749c14990d7f257a27b654aa9258f565b42c47dcf2` |
| `extension/background.js` | `3de6118e2d3bac81cc212a0e4dc1d9d6e2d355731e5fd5dd7f196c71be89a9dd` |
| `extension/content.js` | `1c0ca238dbf287ad6f0a01660c1a7f1ebf78b5e8c1806c5d8c81d5d012391406` |
| `extension/manifest.json` | `959903799ad2983319e0dfda331785c0587b04bea1fe4aef7e8fc0d320e75957` |
| `extension/popup.css` | `4a039180f81b14f2d7df77416a0fe92eb0b1e664d871de2c30e01928a6a61b2f` |
| `extension/popup.html` | `5d5088947ca73192be81383fc01a111f953e715d8c3acace2cdb39e6676d88ea` |
| `extension/popup.js` | `cb382296129a0c3f3660a0d0e4ea1986c1e22517235b92dc648a3d4f9aade7fc` |
| `extension/README.md` | `9e56d58307e903991251ad7e691823e775cac6c1e77b31fa99b16f3033533e9b` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |
| `extension/test_act_bootstrap_hook.js` | `ccc2ae36c46dc3624237dce1a94eb14a33ddd8db8d6984fa86eaa8b77de91e82` |
| `extension/test_completion_marker_guard.js` | `69f692f36a454bc3c91e767dd6a4c1ca5b3efa27bcbb87671c636641aef8e015` |
| `extension/test_conversation_rename.js` | `425638a6a761f91d63d436993e19eabf009b99289f964887d0f6172957158ecd` |
| `extension/test_endpoint_presence.js` | `9fa2a68c2475b2d310f6b3413c2d6d063c8ee41d3f1a31a7cb5eb57cdd04b7a6` |
| `extension/test_full_result_capture.js` | `15e12a226a9d62e9d4046ec6efc05160983f812ead7b2280cfa8c92772a2f33b` |
| `extension/test_identity_guard.js` | `5deafa1e96741644949887fe6e219fdb98f71c4489cf1de3dd4b4d2fd5d2bffc` |
| `extension/test_relay_core.js` | `303802bed62a545b944da3dd96cfcd12e8ace8d320552259b7295de5c8dd8ef6` |
| `extension/test_relay_lightweight_identity.js` | `9acaebf0b16a1bf1c3aa804e9a8da1c85d24e768d4f3d47f8d614cd92a6b244a` |
| `extension/test_window_state_presence.js` | `42bb896055f3afc0a31d99263c19f4fa6993d7a1c379328de62731c3d1a48727` |
| `native-host/RelayNativeHostV2.cs` | `164695e660a775b08d5d3289ff95340e28adb319a65d45e6e88790f4d1ee24ab` |
| `native-host/com.ai_workspace_relay.host.v2.json` | `6358254cb45cd84c3821eac52ed5ef57e2f2ebafec5fbb91055e04dc348b31fd` |

## BCT RCC 1.0.2 editor send-button readiness acceptance candidate

Issue #57 adds an exact text gate before sending, waits for the composer-local
visible enabled send-arrow control, checks the editor and button a second time
immediately before clicking, and forbids keyboard Enter fallback for newly
created ChatGPT tabs. It does not resend previous UNKNOWN submissions and keeps
existing network-versus-DOM receipt instrumentation.

Candidate extension payload SHA-256 for 1.0.2:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `c98195324962ca63711cf8a98e6de9641aeaf3458ca012fdbcf9d36a03f4d90b` |
| `extension/content.js` | `5af022ebf266f505baac254285c4b148713ee748229eb96d74ec0753ad824b0f` |
| `extension/manifest.json` | `8c878c7db1f2d264161c30f6b3c120d397a489154666be63e8b784b43d48b640` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |

## BCT RCC 1.0.5 exact terminal DOM recovery candidate

The first 1.0.4 LIVE tab proved a submitted request and completed network in
the exact created conversation, but the navigation-disconnected content port
left the durable result pending. Version 1.0.5 permits one result-only recovery:
after network completion, it verifies the pending composed fingerprint, exact
instance/tab/window and conversation, finds exactly one matching user turn and
a completed assistant turn, then persists that reply. It never clicks the send
button and never dispatches the prompt again. The same path safely reconciles
the already-UNKNOWN parent operation.

Candidate extension payload SHA-256 for 1.0.5:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `504d34d515a5855d826e30d5c1e0d195badfd89a3af421181b8f47072c7e4a22` |
| `extension/content.js` | `2c0c05e28bdc2e18862da05a159ef2a4f49fe818ae1bca98dc86539258e11242` |
| `extension/manifest.json` | `8427dd109c65b24f4924156b3e6fc57abef591ca3f2234123f677ceae910efb5` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |

## BCT RCC 1.0.6 exact-turn terminal override candidate

The first 1.0.5 reconciliation found the exact submitted turn and its completed
assistant response, but an inert stop control elsewhere in the retained document
caused the result-only recovery to classify it as still streaming. Version 1.0.6
may ignore that stale signal only when the exact routed turn has both
`data-talvt-turn-state=complete` and a completion action UI. The path remains
result-only and never clicks or resubmits.

Candidate extension payload SHA-256 for 1.0.6:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `13c6dedd62e313ea6e5d0a24d6c82da85517de0bf26c1476b4229e0d580316f2` |
| `extension/content.js` | `1f3976bf66947e73fcb37df50048712ac76d20a3cceb9c362b1f1ea180ef0af8` |
| `extension/manifest.json` | `5531360bfdbc10e5030fb55ae2b6601ec7b2fcfaecd86cf34edc0b391ac02ace` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |

## BCT RCC 1.0.7 common terminal classifier candidate

The one-shot independent-window E2E delivered exactly one prompt and received
the exact expected answer, but the normal final-response classifier produced the
same stale-stop false negative before the 1.0.6 recovery helper ran. Version
1.0.7 applies the same dual exact-turn terminal requirement to the common
classifier: both completed turn state and completion action UI are required to
override a stop/generating signal. Either signal alone stays fail-closed.

Candidate extension payload SHA-256 for 1.0.7:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `a6518a52f17c10ec463454506fefb8daf8035b85a84ddd7c7206311d415536e4` |
| `extension/content.js` | `82067236285442ca1c38685027e750736cb787bb674b13fa6452eecd63fcdcb2` |
| `extension/manifest.json` | `2338ae089c439c1915c8b10bc5c90e5df00789176d108be187db129c6e047dc1` |
| `extension/relay_core.js` | `b74d8d5528eb7eaf60600ca3a046da351295c99f7bec1dfebf9b8f21192b2a31` |

Promotion to LIVE requires exact-file backup, clean official main SHA,
existing-tab preservation, loaded backgroundBuildId
`2026-10-13-rcc-editor-gate-v1`, and a distinct one-shot bootstrap E2E.

For a first-message route transition that closes the original content-script
response port, 1.0.2 waits for the exact created tab to acquire one conversation
identity and for that conversation to render exactly one matching user turn.
It also requires the background-observed conversation POST request identity
before returning `SUBMITTED_RECOVERED_AFTER_NAVIGATION`; otherwise the original
`SUBMIT_UNKNOWN` fence remains.

## BCT RCC 1.0.8 durable orchestration binding candidate

Version 1.0.8 adds an exact attachment fence to existing-conversation sends.
The immutable dispatch fingerprint includes the binding receipt, message digest,
RCC instance/session, tab, conversation, and attachment generation. The current
registration is checked before durable pending persistence, immediately before
editor mutation, and synchronously immediately before the send click. Final
authorization atomically issues a bounded 15-second pre-submit lease; binding,
role relocation, and session/tab rebind mutations fail closed until the exact
content sender consumes that lease immediately after its one click. The submit
ACK, worker result, and durable receipt carry the consumed lease attestation, and
expired leases are removed without authorizing a retry.

Candidate extension payload SHA-256 for 1.0.8:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `d43b210d35cc2fe84213bcd8987bfd897920c278da373de619508e773e36deae` |
| `extension/content.js` | `0b3fcf472654c0bfd8309606d1bb22edec88a80d911bdd3cd90b5ab2f6d65954` |
| `extension/manifest.json` | `e417486dedb41a0f3c53c871c7441f46bccf13f2f613190a32c3cc62f211625c` |
| `extension/relay_core.js` | `b74d8d5528eb7eaf60600ca3a046da351295c99f7bec1dfebf9b8f21192b2a31` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-v1` before any orchestration E2E.

## BCT RCC 1.0.9 orchestration recovery candidate

Version 1.0.9 records the activation boundary immediately before the exact
click/Enter transition, returns an opt-in submit ACK before response collection,
and scopes completion detection to the exact routed turn. Confirmed failures
before activation are `NOT_APPLIED`; outcomes at or after activation remain
`UNKNOWN` and retain their durable evidence. This prevents a later manual user
turn from blocking collection of an already completed assignment without making
an ambiguous external effect retryable.

Candidate extension payload SHA-256 for 1.0.9:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `97067a9621a55874be6674e20d8d61641a58feaff6ae97d284deb853e7044ca6` |
| `extension/content.js` | `5de54c3a5c142241cf09e478f8b93a2a5cd8d26d788eaaeed38711b090b69569` |
| `extension/manifest.json` | `8c3aa22004320c1c847128a84f61b442b2c3ccd78a2d5a2d5bd216946d588b31` |
| `extension/relay_core.js` | `b74d8d5528eb7eaf60600ca3a046da351295c99f7bec1dfebf9b8f21192b2a31` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-recovery-v2` before a fresh orchestration E2E.

## BCT RCC 1.0.10 stale-completion drain candidate

Version 1.0.10 preserves the 1.0.9 activation and exact-turn fences and closes
one result-return recovery gap found by the first fresh-node chain. A bootstrap
reply can be recovered and durably persisted by the background while the
content script has already exhausted its bounded result-delivery retries. In
that case the content script retained a `completed` execution record, so the
next exact assignment was safely deferred but could not drain. A new exact
relay now first retries only the idempotent prior result receipt. If that clears
the record, normal exact submission continues; otherwise the new relay returns
confirmed `NOT_APPLIED` and is never queued. Exact orchestration also returns
`NOT_APPLIED` while the target is generating. Pre-1.0.10 orchestration queue
entries lack their binding tuple, so drain drops those local entries before
submit and leaves the background evidence for explicit reconciliation. Generic
deferred entries preserve any supplied binding tuple.

Candidate extension payload SHA-256 for 1.0.10:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `75a1189b0a00a974e4183e65e49b9adb3ed755ad3151fec4dcca7884f284bf23` |
| `extension/content.js` | `fc2c365ebf44a023c36a6522540c6e03e86eebb0e9997e00dfec38cdf6451c2a` |
| `extension/manifest.json` | `64e462c602842d888f6ddd959dab555dcb06f85e4634162e83ad1cada2f7312b` |
| `extension/relay_core.js` | `b74d8d5528eb7eaf60600ca3a046da351295c99f7bec1dfebf9b8f21192b2a31` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-recovery-v3` before resuming the queued chain.

## BCT RCC 1.0.11 durable conversation identity candidate

Version 1.0.11 excludes ChatGPT's transient `/c/local-chatgpt` optimistic route
from the conversation identity contract. Fresh-tab submission now waits for the
durable server-assigned conversation key before it records or attests the
bootstrap execution. Content and background both use the same `RelayCore`
parser, preventing a provisional route from leaving a completed execution
record bound to a different final conversation. The 1.0.10 busy-target and
late-submit fences remain unchanged.

Candidate extension payload SHA-256 for 1.0.11:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `9d9e698a38ee725e0cc81ba55b33386ee14bb71e7abefa1cac5b9b31b1c0fa8a` |
| `extension/content.js` | `7d07a34f03cc81dd6622bc455f3ec9c6d85fcdb542668af37d1ebd2484c9c6bc` |
| `extension/manifest.json` | `9c227fa92cce5e416afe9b49983158296bcb23b14c943a85d7caa033a4acbd73` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

## BCT RCC 1.0.15 exact draft stabilization candidate

Version 1.0.15 retains the 1.0.14 canonical-editor reacquisition and adds a
bounded 1.2-second observation window for ChatGPT's asynchronous ProseMirror
normalization after the input event. Submission remains impossible unless the
current canonical editor reaches the exact normalized requested draft. A
missing, different, or subsequently replaced editor still fails closed, and
the exact binding authorization and single-use pre-submit lease remain
mandatory.

The runtime build identifier is
`2026-10-14-rcc-orchestration-recovery-v8`. The candidate requires the full RCC
JavaScript suite plus an isolated fresh-run orchestration E2E before acceptance.

Candidate extension payload SHA-256 for 1.0.15:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `7945812ed5a143cd8a76e1980e836646918fb7b9914bcc8cbd2030fe7ef1efe4` |
| `extension/content.js` | `28fd0e85087f786b83ee64fbcb5239e3fb65f108f5955ad540fe7afe26a741f3` |
| `extension/manifest.json` | `e0f794f04e96b6e1056ce77e9802d64446564b91eae4943e75b7bb82cd05b490` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-recovery-v4` before a fresh bootstrap/E2E.

## BCT RCC 1.0.16 result-only orchestration recovery candidate

The first bounded manager/worker acceptance on 1.0.15 submitted exactly once,
received a submit ACK, and rendered the exact final response, but ChatGPT's
conversation request ended with `net::ERR_ABORTED` while the turn router had
not yet resolved the new DOM turn. The durable failure receipt preserved
`RELAY_FINAL_DOM_NOT_READY:ROUTE_TURN_NOT_RESOLVED` in `failureEvidence`, but
the existing result-only recovery classifier inspected only the top-level
error and orchestration never invoked that recovery path.

Version 1.0.16 recognizes the bounded failure-evidence fields and
`net::ERR_ABORTED` as recovery candidates. Orchestration may then invoke one
exact `recover-pending` lookup and re-read the same durable relay ID. This path
requires the original persisted receipt and exact role, tab, conversation,
binding receipt, instance/session, attachment generation, prompt fingerprint,
and result hash. It never calls the send command and leaves insufficient or
non-matching evidence UNKNOWN.

The runtime build identifier is
`2026-10-14-rcc-orchestration-recovery-v9`. Promotion requires the full Python
and RCC JavaScript suites plus the staged single manager/worker LIVE gate.

Candidate extension payload SHA-256 for 1.0.16:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `0cb5bb5443fbb3075cbadc23e09efb5320e441f9dbe40fc32a2c8d48e205de0b` |
| `extension/content.js` | `ed000c5658777b3df538c5a8ae1e5e31ddca20c4fe215509f744170dc20d4cc3` |
| `extension/manifest.json` | `924ecc447798007dc9afb4ed03fa7dc5361216f7168afd04d5f0cfc4fef815be` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

## BCT RCC 1.0.17 canonical turn recovery candidate

The first LIVE result-only recovery candidate still returned UNKNOWN after the
exact assignment and exact assistant result were both rendered. Read-only DOM
diagnostics showed nested compatibility and semantic wrappers for the same
logical turn and message units. The route collector treated those wrappers as
separate candidates, so the exact submitted turn could not be resolved.

Version 1.0.17 canonicalizes a wrapper with one `data-turn-key` descendant to
that keyed turn and prefers the one semantic message unit nested inside a
legacy author-role wrapper. A structured content-recovery failure now invokes
the existing direct DOM recovery path; a failed direct recovery preserves the
original durable receipt but reports `recovered=false` instead of advertising
the unchanged failure as recovered. Neither recovery path sends a message.

The runtime build identifier is
`2026-10-14-rcc-orchestration-recovery-v10`. Promotion requires the full Python
and RCC JavaScript suites plus a fresh single manager/worker LIVE gate before
any multi-worker chain.

Candidate extension payload SHA-256 for 1.0.17:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `95523761698dde4c2f35d6c147cae0ab9a875a77d6c008958bdff988a1b2c2da` |
| `extension/content.js` | `4d78084524018b634e3cda2d302953a6825afd9d50f4957957e535d19c05eb32` |
| `extension/manifest.json` | `9fe7855146f17ff2119781054b7a780e194db557d74c551c1740588e82175119` |
| `extension/relay_core.js` | `b3ad92bc20564a905bffc37f3e524e2c8e8c5ae71c02517a301cedd5cf1341cd` |

## BCT RCC 1.0.12 durable result and composer candidate

Version 1.0.12 closes two fail-closed conditions found by the first 1.0.11
chain attempt. The content script can now discard a stale completed execution
record only after the background proves an exact, tab- and
conversation-matched `RESULT_PERSISTED` receipt. It does not replay the prompt
or the result. The composer verifier also reconstructs adjacent ProseMirror
paragraphs with their inserted newline, avoiding a false
`RELAY_EDITOR_TEXT_MISMATCH` caused solely by browser `innerText` layout
spacing. Actual draft differences still fail before submit.

Candidate extension payload SHA-256 for 1.0.12:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `749900bcbd09ea6b6f443322b68a0d25e019a210d495b6bb174f06912edea442` |
| `extension/content.js` | `f06975504b6dcd23d6c4860e351b9ee80c3b2b4a2213f5f960358ae3239c9670` |
| `extension/manifest.json` | `6ff255c6d17944b962693f096ae31cb1ab1a0da3ed137de86f30e84ecf59055b` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-recovery-v5` before the next fresh-run E2E.

## BCT RCC 1.0.13 background-recovered submit candidate

Version 1.0.13 generalizes the exact durable-receipt cleanup from 1.0.12 to a
content record still marked `submitted`. This state occurs when the background
recovers the completed exact DOM result and persists it before the original
content-side collector finishes. The cleanup still requires the exact
`RESULT_PERSISTED` receipt, tab, and durable conversation key; absent that
proof, the submitted record remains fail-closed and blocks a new prompt.

Candidate extension payload SHA-256 for 1.0.13:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `c77b26418e4070223531b04446a1a403dbc1444fce6d400945fc87771c51a0e7` |
| `extension/content.js` | `fa8bd0590540b0b413ae525873556fe369c3f3aafc8502153512852ab47629ef` |
| `extension/manifest.json` | `5a8df5b6b2fb9d2cb095c0969acac08ecb98f5a5c82c17baeb4a454d7376a0e6` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

Loaded-build acceptance requires `backgroundBuildId` exactly
`2026-10-14-rcc-orchestration-recovery-v6` before the next fresh-run E2E.

## BCT RCC 1.0.14 ProseMirror editor replacement candidate

Version 1.0.14 keeps the exact draft, tab, conversation, binding receipt,
attachment generation, and pre-submit lease fences while allowing ChatGPT's
ProseMirror composer to replace its contenteditable DOM node after the input
event. RCC reacquires the canonical composer and proceeds only when that live
editor contains the exact normalized draft. A changed or missing draft remains
`RELAY_EDITOR_TEXT_MISMATCH` and no submit activation occurs.

The runtime build identifier is
`2026-10-14-rcc-orchestration-recovery-v7`. The candidate requires the full RCC
JavaScript suite plus an isolated fresh-run orchestration E2E before acceptance.

Candidate extension payload SHA-256 for 1.0.14:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `9cba648243a0301369529bdff7cdcdab1cbb36c693fd6b187dff1040630eb76c` |
| `extension/content.js` | `878c740df9c768915b1dd2e73f9ce2d23859f3a13703bc2d20d5adc5788393ae` |
| `extension/manifest.json` | `68b63efcb3da7e104eaf0d155b0db13b8406967b54e6477d75960464644b20c8` |
| `extension/relay_core.js` | `74c26a834b47743876262c33a5bea03bc809070235642513ca42b860b52581fc` |

## BCT RCC 1.0.3 bootstrap conversation identity acceptance candidate

The first 1.0.2 LIVE E2E proved that ChatGPT can replace the blank route with a
new conversation while the content-side final reply validator is still using a
provisional identity. Version 1.0.3 permits that validator to rebind only for a
newly created bootstrap tab whose pre-submit turn set was empty and whose new
conversation contains exactly one new user turn matching the exact submitted
text. Existing conversations, non-bootstrap sends, non-empty histories,
missing identities and ambiguous matching turns remain fail-closed.

Candidate extension payload SHA-256 for 1.0.3:

| File | SHA-256 |
| --- | --- |
| `extension/background.js` | `c98195324962ca63711cf8a98e6de9641aeaf3458ca012fdbcf9d36a03f4d90b` |
| `extension/content.js` | `4c564336cfeb5e9dd8e5fbc21409b055a1ceec16887ab258a846850518ad1da6` |
| `extension/manifest.json` | `2030720bd299c65cb5766acdff4256de127874b69bbabb7214ad8e4cc8e5d294` |
| `extension/relay_core.js` | `27d95fdaa6bd3586ff3aa2cb9279edaf02725a44afad374a3da6b3f7261adc91` |
