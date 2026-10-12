# GitHub operations module

This module owns the operational contract for pull requests, CI, canonical
main synchronization and the small runner pool used by BCT-managed work.
Implementation adapters currently live in `src/bct/features/github.py` and
`src/bct/integrations/github.py`; this directory documents the installable
module boundary without introducing a plugin loader.

