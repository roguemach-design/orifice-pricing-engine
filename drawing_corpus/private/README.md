# Private corpus staging

This directory is intentionally ignored. Never commit proprietary drawings here.
Use approved restricted storage and opaque references when a real corpus is added.

Phase 1D private audit manifests use `manifest_version: "1.0"` and contain one
record per source document with a stable source-group ID, document classification,
expected document class/candidate count, and optional per-region field truth.
Derived regions from one sheet retain one source-group ID and are never counted as
independent customer drawings. Run the generic harness with:

```bash
python -m drawing_intake.corpus_audit \
  --private-root <private-directory> \
  --manifest <private-manifest.json>
```
