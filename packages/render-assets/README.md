# Render assets and profiles

`catalog.json` freezes the two render profiles and every external file consumed by the Blender
worker. The API verifies byte counts and SHA-256 values at startup. The runtime never calls the
Poly Haven API.

- `preview`: 1280×720 EEVEE overview, compatible with the previous single-image workflow.
- `quality`: 1920×1080 Cycles, Metal preferred, adaptive sampling, denoising, HDRI and wood-floor
  PBR maps, with overview, living-room and bedroom views.

All committed external files are 1K CC0 snapshots. Source pages and exact download URLs remain
in the catalog for auditability.
