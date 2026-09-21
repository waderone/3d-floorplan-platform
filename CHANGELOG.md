# Changelog

All notable changes to this project will be documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project intends to use [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Reject path traversal at the artifact-store boundary and rasterize uploaded
  annotation images before inserting them into the SVG workspace.

## [0.1.0] - 2026-09-21

### Added

- Open-source license, contribution guide, security policy, code of conduct,
  and third-party notices.
- Continuous integration for Python and JavaScript tests and builds.
- Dependabot configuration and CodeQL security scanning.
- Public, reproducible Pascal Editor baseline submodule.

### Changed

- Consolidated the implemented MVP modules onto the default branch.
- Clarified which editor integration, production infrastructure, and dataset
  capabilities are not yet part of the public baseline.
- Upgraded glTF-Transform to 4.5.0 and Starlette to the patched 1.x line;
  JavaScript and Python dependency audits now run in CI.

[Unreleased]: https://github.com/waderone/3d-floorplan-platform/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/waderone/3d-floorplan-platform/releases/tag/v0.1.0
