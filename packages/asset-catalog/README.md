# Product asset catalog

`catalog.json` is the audited runtime contract shared by the API, Web Viewer, and Blender
worker. `asset-catalog.schema.json` defines its portable JSON structure; the API adds
cross-reference and on-disk SHA-256 validation. Model files are normalized to meters, Y-up,
centered on the floor, and delivered as GLB. A model load failure must use the catalog's
explicit procedural fallback.

Catalog v9 supports multiple audited sources, kitchen/bathroom room recipes, living-room focal
fixtures, and explicit model material handling. `replace`
uses the selected style role, `tint` keeps embedded PBR textures while multiplying the style
color, and `preserve` keeps the authored materials. The starter set retains Kenney's tiny CC0
fallbacks and adds fixed Poly Haven 1K glTF snapshots for the sofa, coffee table, wooden cabinet,
pendant, plants, wall art and ceramic decor. The living-room sofa, coffee table and wooden cabinet
retain their authored 1K PBR textures for high-end client demonstrations; secondary assets remain
deterministically reduced where appropriate. Every source and local license notice remains part of
startup validation.

The commercial bedroom benchmark replaces the former box-built bed with a 23-part upholstered
bed set: a sculpted duvet, folded throw, four pillows, lumbar cushion, channel headboard and
embedded 512 px Cotton Jersey diffuse/normal/roughness textures. A separate 29,860-byte relief
art asset provides a reusable wall focal point. Both generators quantize modifier output to a
binary-exact grid so two independent Blender runs produce identical GLBs. The bed uses `tint`,
preserving its fabric maps while responding to the selected style role.

The project-authored interior fixture generator adds an oak kitchen suite, a bathroom vanity/
toilet/shower suite, a sculptural planter, and a stone-topped bedside table with a linen-shade lamp.
The v2 kitchen includes an oven, hood, sink, hob, worktop props, and cabinet lighting; the v2
bathroom includes framed mirror lighting, double-sided vanity details, shower controls, towel rail,
toilet flush, and shower tray. All four are committed as CC0 GLBs with fixed generator and delivery
hashes; the complete model catalog is 7,279,848 bytes and remains below the 8 MiB high-end mobile
demonstration budget.
The project-authored living-room focal generator adds a slim television and a brass/linen floor
lamp. Both use preserved PBR materials, fixed hashes, and explicit recipe sizing so the client
close-up stays compositionally balanced.

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

The generator downloads three integrity-pinned Cotton Jersey maps from Poly Haven, embeds
deterministically scaled 512 px textures, and exports quantized organic cloth meshes. Two
independent runs with the fixed hash seed must match the catalog byte count and SHA-256 exactly.

Regenerate the project-original CC0 bedroom relief art:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_bedroom_wall_art.py -- \
  --output packages/asset-catalog/models/project-warm-minimal-bedroom-art.glb \
  --report /tmp/project-bedroom-art-report.json
```

Regenerate the project-original interior fixtures one asset at a time:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset kitchen \
  --output packages/asset-catalog/models/project-warm-minimal-kitchen.glb \
  --report /tmp/project-warm-minimal-kitchen.json
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset bathroom \
  --output packages/asset-catalog/models/project-warm-minimal-bathroom.glb \
  --report /tmp/project-warm-minimal-bathroom.json
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset planter \
  --output packages/asset-catalog/models/project-sculptural-planter.glb \
  --report /tmp/project-sculptural-planter.json
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_interior_fixtures.py -- --asset bedside-table \
  --output packages/asset-catalog/models/project-warm-minimal-bedside-table.glb \
  --report /tmp/project-warm-minimal-bedside-table.json
```

Regenerate the project-original living-room focal fixtures one asset at a time:

```bash
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_living_focal_fixtures.py -- --asset television \
  --output packages/asset-catalog/models/project-modern-television.glb \
  --report /tmp/project-modern-television.json
PYTHONHASHSEED=0 blender --background --factory-startup --disable-autoexec --python-exit-code 1 \
  --python tools/assets/generate_living_focal_fixtures.py -- --asset floor-lamp \
  --output packages/asset-catalog/models/project-brass-floor-lamp.glb \
  --report /tmp/project-brass-floor-lamp.json
```
