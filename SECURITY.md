# Security Policy

## Supported versions

Only the latest release receives security fixes. Older releases are archived
on the Releases page for reproducibility only.

| Version | Supported |
|---------|-----------|
| 9.0.x   | ✅ |
| < 9.0   | ❌ |

## Reporting a vulnerability

**Please do not open public GitHub issues for security problems.**

Instead, open a
[private security advisory](https://github.com/SysAdminDoc/UniFile/security/advisories/new)
on GitHub. This notifies the maintainer privately and provides a space to
coordinate a fix before disclosure.

Include in your report:

- A description of the vulnerability
- Affected version(s)
- Steps to reproduce (ideally a minimal proof-of-concept)
- Impact: what an attacker could do with this
- Any suggested mitigation

You should get an initial response within 7 days. If the issue is confirmed,
a patched release will be published and credited in the release notes
(unless you prefer to remain anonymous).

## Scope

**In scope**
- Path-traversal / data-loss bugs in move/rename/apply flows
- Code-execution via crafted files (malicious images, archives, media)
- Secrets exposure (API keys, local paths) through logs or CSV exports
- SQL injection in tag library queries
- Unsafe deserialization (pickle, JSON, YAML, XML)
- Crash-on-input DoS that persists across restarts

**Out of scope**
- Issues requiring physical or root access to the machine UniFile is running on
- Vulnerabilities in upstream dependencies (please report to the upstream project)
- Social-engineering scenarios against the user
- Known behavior of GPL-licensed bundled dependencies (PyQt6)
