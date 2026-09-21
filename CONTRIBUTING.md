# Contributing

Thank you for helping improve 3D Floorplan Platform. Bug reports, documentation
fixes, tests, accessibility improvements, and focused implementation changes
are welcome.

## Before opening a change

1. Search existing issues and pull requests.
2. Open an issue before making a large architectural or data-model change.
3. Never submit customer plans, private datasets, credentials, or assets whose
   redistribution rights have not been verified.
4. Keep pull requests focused and explain user-visible behavior and known
   limitations.

## Development setup

Clone with the public editor baseline:

```bash
git clone --recurse-submodules https://github.com/waderone/3d-floorplan-platform.git
cd 3d-floorplan-platform
```

The API requires Python 3.11 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r services/api/requirements-dev.txt
python -m pytest services/api/tests -q
```

The JavaScript packages require Node.js 22.12 or newer:

```bash
for package in apps/viewer apps/annotator workers/model; do
  (cd "$package" && npm ci && npm test && npm run build --if-present)
done
```

See the README in each app or service for component-specific run commands.

## Pull requests

- Add or update tests for behavior changes.
- Run the Python and JavaScript test suites relevant to the change.
- Update documentation, schemas, and ADRs when contracts change.
- Record third-party asset provenance, license, source URL, and integrity hash.
- Use clear commit subjects; Conventional Commits are encouraged.
- Confirm that generated files, local data, and secrets remain ignored.

By contributing, you agree that your contribution is licensed under the
repository's MIT License. Third-party materials must retain their original
license and attribution.
