# Security policy

## Supported versions

Security fixes are currently applied to the latest commit on `main`. The
project is pre-1.0 and does not yet provide long-term support for older
releases.

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability. Use GitHub's
**Report a vulnerability** flow in the repository Security tab to send a
private report to the maintainers. Include:

- the affected component and commit or version;
- reproduction steps or a minimal proof of concept;
- the expected impact and any known mitigations;
- whether the report involves uploaded floorplans, generated artifacts, or
  third-party assets.

The maintainers will acknowledge a complete report within seven days and will
coordinate validation, remediation, and disclosure. Timelines may vary with
severity and maintainer availability.

## Security boundaries

The current implementation is a development/MVP system. In particular, the
local API has no authentication, permits broad development CORS, and uses
single-process local storage. Do not expose it directly to the public internet
or use it for confidential floorplans. Production deployments must add access
control, tenant isolation, restricted CORS, durable storage, malware/content
validation, rate limits, and a managed task queue.
