# Product asset catalog

`catalog.json` is the audited runtime contract shared by the API, Web Viewer, and Blender
worker. `asset-catalog.schema.json` defines its portable JSON structure; the API adds
cross-reference and on-disk SHA-256 validation. Model files are normalized to meters, Y-up,
centered on the floor, and delivered as GLB. A model load failure must use the catalog's
explicit procedural fallback.

Catalog v2 supports multiple audited sources and explicit model material handling. `replace`
uses the selected style role, `tint` keeps embedded PBR textures while multiplying the style
color, and `preserve` keeps the authored materials. The starter set retains Kenney's tiny CC0
fallbacks and adds fixed Poly Haven 1K glTF snapshots for modern armchairs, an alternate sofa,
a bed, and a pendant light. Every source and local license notice remains part of startup validation.

Regenerate the committed GLBs from an audited extraction of the official ZIP:

```bash
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/convert_kenney_furniture.py -- \
  --source-root "/path/to/Models/OBJ format" \
  --output-directory packages/asset-catalog/models \
  --report /tmp/kenney-conversion-report.json
```

The source archive is not committed. Its URL and SHA-256 are frozen in `catalog.json`.

Regenerate the committed Poly Haven GLBs from fixed, integrity-checked source files:

```bash
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/import_polyhaven_models.py -- \
  --output-directory packages/asset-catalog/models \
  --report /tmp/polyhaven-import-report.json
```

The importer pins every separate glTF dependency by byte count and MD5, emits SHA-256 values in
its report, and embeds textures in the delivered GLB. It does not query a mutable asset catalog at
runtime.
