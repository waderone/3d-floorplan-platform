# Render assets and profiles

`catalog.json` freezes the two render profiles and every external file consumed by the Blender
worker or realtime Viewer. The API verifies byte counts and SHA-256 values at startup and exposes
the frozen files under `/render-assets`. The runtime never calls the Poly Haven API.

- `preview`: 1280×720 EEVEE overview, compatible with the previous single-image workflow.
- `quality`: 1920×1080 Cycles, Metal preferred, adaptive sampling, denoising, HDRI and wood-floor
  PBR maps, with overview, living-room and bedroom views.

The HDRI, wood floor, and natural rug are committed as audited 1K CC0 snapshots. Their original
download URLs and exact delivery hashes remain in the catalog; the realtime Viewer uses 16×
anisotropic filtering for the warm-minimal floor and rug.
