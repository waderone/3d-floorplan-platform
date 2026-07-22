# Product asset catalog

`catalog.json` is the audited runtime contract shared by the API, Web Viewer, and Blender
worker. `asset-catalog.schema.json` defines its portable JSON structure; the API adds
cross-reference and on-disk SHA-256 validation. Model files are normalized to meters, Y-up,
centered on the floor, and delivered as GLB. A model load failure must use the catalog's
explicit procedural fallback.

Catalog v4 supports multiple audited sources, kitchen/bathroom room recipes, and explicit model material handling. `replace`
uses the selected style role, `tint` keeps embedded PBR textures while multiplying the style
color, and `preserve` keeps the authored materials. The starter set retains Kenney's tiny CC0
fallbacks, adds fixed Poly Haven 1K glTF snapshots for modern armchairs, an alternate sofa and a
pendant light, and uses a reproducible project-original modern upholstered bed. Every source and
local license notice remains part of startup validation.

The project-authored interior fixture generator adds an oak kitchen suite, a bathroom vanity/
toilet/shower suite, and a sculptural planter. All three are committed as CC0 GLBs with fixed
generator and delivery hashes; the complete model catalog remains below the 5 MiB mobile budget.

Regenerate the committed GLBs from an audited extraction of the official ZIP:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/convert_kenney_furniture.py -- \
  --source-root "/path/to/Models/OBJ format" \
  --output-directory packages/asset-catalog/models \
  --report /tmp/kenney-conversion-report.json
```

The source archive is not committed. Its URL and SHA-256 are frozen in `catalog.json`.

Regenerate the committed Poly Haven GLBs from fixed, integrity-checked source files:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/import_polyhaven_models.py -- \
  --output-directory packages/asset-catalog/models \
  --report /tmp/polyhaven-import-report.json
```

The importer pins every separate glTF dependency by byte count and MD5, emits SHA-256 values in
its report, and embeds textures in the delivered GLB. It does not query a mutable asset catalog at
runtime.

Regenerate the project-original CC0 modern bed:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_modern_bed.py -- \
  --output packages/asset-catalog/models/project-modern-upholstered-bed.glb \
  --report /tmp/project-modern-bed-report.json
```

The generator rejects an unset hash seed, exports triangle-only organic meshes,
omits unused texture coordinates, and enables Meshopt delivery compression. Two
independent runs must match the catalog byte count and SHA-256 exactly.

Regenerate the project-original interior fixtures one asset at a time:

```bash
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset kitchen \
  --output packages/asset-catalog/models/project-warm-minimal-kitchen.glb \
  --report /tmp/project-warm-minimal-kitchen.json
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset bathroom \
  --output packages/asset-catalog/models/project-warm-minimal-bathroom.glb \
  --report /tmp/project-warm-minimal-bathroom.json
blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset planter \
  --output packages/asset-catalog/models/project-sculptural-planter.glb \
  --report /tmp/project-sculptural-planter.json
```
