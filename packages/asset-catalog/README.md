# Product asset catalog

`catalog.json` is the audited runtime contract shared by the API, Web Viewer, and Blender
worker. `asset-catalog.schema.json` defines its portable JSON structure; the API adds
cross-reference and on-disk SHA-256 validation. Model files are normalized to meters, Y-up,
centered on the floor, and delivered as GLB. A model load failure must use the catalog's
explicit procedural fallback.

The starter set is derived from Kenney Furniture Kit. The official asset page labels the web
release `1.0`; the downloaded package license identifies the archive as Furniture Kit `2.0`.
Both values are retained in provenance instead of guessing a replacement version.

Regenerate the committed GLBs from an audited extraction of the official ZIP:

```bash
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/convert_kenney_furniture.py -- \
  --source-root "/path/to/Models/OBJ format" \
  --output-directory packages/asset-catalog/models \
  --report /tmp/kenney-conversion-report.json
```

The source archive is not committed. Its URL and SHA-256 are frozen in `catalog.json`.
