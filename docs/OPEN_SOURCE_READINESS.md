# Open-source release readiness

This checklist records the repository work required before the first public
release. It deliberately separates changes that are safe to prepare locally
from external actions that require a maintainer decision.

## Completed in the repository

- [x] Move the implemented MVP history onto the local default branch.
- [x] Add an MIT license for project-authored code and documentation.
- [x] Add third-party and asset licensing notices.
- [x] Point the editor submodule at a public, immutable upstream commit.
- [x] Add contribution, security, and community conduct policies.
- [x] Add Python and JavaScript CI, CodeQL, and Dependabot configuration.
- [x] Document reproducible setup, test commands, current limitations, and
      the pre-1.0 support policy.
- [x] Keep private images and local processing outputs excluded from Git.
- [x] Scan tracked text for common credential patterns; no credential-shaped
      values were found in the current tree.

## Maintainer decisions required before publishing

- [x] Obtain maintainer approval to rewrite Git history so author metadata uses
      the GitHub noreply address and the former private editor mirror URL is
      removed from historical repository content.
- [x] Scan all 36 rewritten commits with Gitleaks 8.30.1; no leaks were found.
- [x] Confirm that the CC0 source and integrity records in all three asset
      catalogs remain accurate at the publication date.
- [x] Push the prepared `main` branch and confirm all CI and CodeQL checks pass.
- [x] Change repository visibility to public only after the preceding checks.
- [x] Enable GitHub private vulnerability reporting, Dependabot security
      updates, secret scanning with push protection, and branch protection.
- [x] Test a clean public clone with `--recurse-submodules` and confirm the
      pinned Pascal Editor baseline is available without private access.
- [ ] Publish `v0.1.0` with release notes only after testing a clean public
      clone with `--recurse-submodules`.

## Community and adoption evidence

These items are not technical blockers, but they materially strengthen an
open-source program application:

- [ ] Publish a redistributable demo and screenshots or a short walkthrough.
- [ ] Label beginner-friendly issues and publish a focused roadmap.
- [ ] Record external users, downstream integrations, downloads, citations,
      and other adoption signals without inflating or estimating metrics.
- [ ] Conduct maintenance in public through issues, pull requests, review,
      and release notes.

Do not claim public availability, user counts, download counts, or a release
until the corresponding external action has actually occurred.
