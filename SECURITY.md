# Security policy

## Supported versions

Security fixes are made for the latest published StreamSnip AI release and the current `master` branch. Older installers are intentionally removed when a newer stable release is published.

## Report a vulnerability privately

Do not open a public issue for vulnerabilities, exposed credentials, authentication bypasses, unsafe file access, command execution, or privacy leaks.

Use GitHub's private vulnerability reporting flow:

<https://github.com/sifat-jaman-13/stream-clip-ai/security/advisories/new>

Include:

- affected version/commit;
- operating system and installation method;
- clear reproduction steps;
- impact and realistic attack scenario;
- a minimal proof of concept, if safe;
- suggested mitigation, if known.

Never include real API keys, tokens, private videos, account IDs, or complete local configuration files. Replace them with test values.

## Deployment assumptions

StreamSnip AI is designed as a single-user local application.

- The web server binds to loopback by default.
- State-changing requests require a per-process token.
- Docker Compose publishes the UI to `127.0.0.1` only.
- The app is not designed to be exposed directly to the public internet or an untrusted LAN.
- Hosted AI and Zernio send data to third-party services only when those features are selected/configured.

Users are responsible for protecting local runtime files such as `ai_settings.json`, `publishing.json`, and `zernio.json`. If a credential appears in logs, screenshots, exported sessions, or public commits, revoke and rotate it immediately.

## Disclosure

Please allow time for the report to be reproduced and a fix to be prepared before public disclosure. Valid reports will be handled on a best-effort basis, with priority based on user impact and exploitability.
