# First-slice provenance

The first BCT implementation was independently authored in this repository after reviewing these current ACT sources at AI-CODE-TEAM commit `b0148ff1530db6d71f0c665c816c95fc575ff3e2`:

- `tools/adc-desktop-control/src/adc_git_engine.py`
- `tools/adc-desktop-control/src/adc_test_runner.py`
- `tools/adc-desktop-control/src/adc_code_tools.py`
- relevant local execution and completion acceptance tests

The retained behavioral ideas are bounded target resolution, explicit expected hashes/HEAD, exact commit path sets, new-file SHA proof, argument-vector process execution, and bounded output. BCT owns the new implementation and tests in this repository. It does not import ACT packages or copy runtime data, credentials, profiles, databases, or logs.

No third-party source was copied into this first slice. Python standard-library components are used.

GitHub integration V1 was independently authored in BCT. It uses the documented `git` command-line
contracts and the official GitHub CLI `gh api` interface. No ACT GitHub implementation, credential,
runtime database, workflow receipt, or token was copied into BCT.
