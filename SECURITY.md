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

- The native desktop engine forcibly binds its API to `127.0.0.1`, `localhost`, or `::1`.
- State-changing requests require a per-process token.
- The app is not designed to be exposed directly to the public internet or an untrusted LAN.
- Hosted AI and Zernio send data to third-party services only when those features are selected/configured.

- AI-provider and Zernio API credentials are stored in the Windows DPAPI-backed credential store in `streamsnip.db`; they are not written to the AI preferences JSON or publishing settings JSON.
- When upgrading from a version that stored AI-provider keys in `ai_settings.json`, the current engine migrates those values into DPAPI storage and removes the plaintext keys after the encrypted write succeeds.
- `ai_settings.json` contains non-secret provider preferences. Local databases, settings, recordings, clips, and runtime logs should still be protected as private user data.
- Current runtime logging redacts registered credentials and common token formats before log entries are displayed or persisted. Logs created by older app builds may still contain earlier diagnostic text.
- If a credential is found in an old log, screenshot, export, or public commit, revoke and rotate it immediately.

## Disclosure

Please allow time for the report to be reproduced and a fix to be prepared before public disclosure. Valid reports will be handled on a best-effort basis, with priority based on user impact and exploitability.
