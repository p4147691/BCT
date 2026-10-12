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

The Native Host transition manifest accepts both IDs while the old instance is inspected and the
verified registrations are rebound to the new exact instance.  It does not copy pending sends or
re-run an old browser operation.  The legacy origin can be removed after the old extension is disabled
and the new instance passes state and duplicate-operation acceptance.

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
| `extension/test_relay_lightweight_identity.js` | `3f647299bb8d2522471b18284ef53195369c3b188aa490e8107935c432b18aa3` |
| `extension/test_window_state_presence.js` | `42bb896055f3afc0a31d99263c19f4fa6993d7a1c379328de62731c3d1a48727` |
| `native-host/RelayNativeHostV2.cs` | `164695e660a775b08d5d3289ff95340e28adb319a65d45e6e88790f4d1ee24ab` |
| `native-host/com.ai_workspace_relay.host.v2.json` | `6358254cb45cd84c3821eac52ed5ef57e2f2ebafec5fbb91055e04dc348b31fd` |
