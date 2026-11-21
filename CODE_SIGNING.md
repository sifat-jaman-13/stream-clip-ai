# Code signing policy

This policy describes how official Windows installer releases for StreamSnip AI are built, reviewed, signed, and published.

## Scope

This policy applies only to the official `StreamSnipAI-Setup.exe` installer published in this repository's GitHub Releases. It does not cover third-party Python packages, FFmpeg, Whisper models, or binaries obtained separately by the app during first-time setup.

The source of truth is:

- Repository: https://github.com/sifat-jaman-13/stream-clip-ai
- Release source branch: `master`
- Build workflow: [Build and publish Windows release](.github/workflows/build-windows-release.yml)

## Ownership and responsibilities

**Sifat Jaman** is the repository owner, project maintainer, and release authority.

The maintainer is responsible for the application source, installer definition, build scripts, GitHub Actions workflow, release metadata, and the decision to publish a release. Changes to application code, dependencies, installer scripts, and CI/build configuration are reviewed by the maintainer before a release is authorized.

SignPath Foundation, if the project is accepted into its Open Source Code Signing program, supplies and controls the signing certificate and protects its private key. The project does not receive or export that private key.

## Release and build procedure

1. Prepare a release-ready commit on the protected/default `master` branch.
2. Review the changes since the previous release, including application source, dependencies, installer files, and all build/CI scripts.
3. Confirm that the version in `pyproject.toml`, `autoclip.py`, and `installer/AutoClip.iss` is identical.
4. Dispatch the Windows release workflow from `master`. The workflow rejects dispatches from other refs.
5. The GitHub-hosted Windows runner runs the regression tests and Python syntax checks, installs the pinned Inno Setup 6.7.4 build tool, and invokes the repository's `build_windows.ps1`.
6. The workflow uploads the unsigned installer to GitHub Actions artifact storage before it requests signing. The build and signing request run on GitHub-hosted infrastructure.
7. When SignPath is configured, the workflow submits that exact workflow artifact to the project's SignPath release-signing policy. It downloads the returned artifact and verifies that Windows reports a valid Authenticode signature. A signing error or invalid signature stops publication; the workflow does not silently publish an unsigned fallback after a signing request fails.
8. The workflow creates or updates the matching GitHub Release and publishes the installer together with a SHA-256 checksum.

The release workflow derives the release tag from the version committed to source control. If that tag already exists, it must point to the exact commit being built; otherwise publication stops.

## SignPath configuration and origin verification

For Open Source Code Signing, the SignPath project must be configured to use the predefined GitHub.com trusted build system, linked to this repository, and configured for origin verification. The release-signing policy should accept the `master` source branch only. The default artifact configuration must accept a single Windows PE executable, because the workflow uploads the installer without wrapping it in an additional ZIP archive.

The GitHub Actions integration uses these repository settings:

- Actions variable `SIGNPATH_ORGANIZATION_ID`
- Actions variable `SIGNPATH_PROJECT_SLUG`
- Actions variable `SIGNPATH_SIGNING_POLICY_SLUG`
- Actions secret `SIGNPATH_API_TOKEN`

All four settings must be present to enable signing. A partial configuration fails the workflow instead of producing a misleading unsigned release.

Until the project is accepted by SignPath and these settings have been configured, the workflow can publish an explicitly unsigned installer with its checksum. The existing unsigned releases remain unsigned; adding this policy does not retroactively sign them.

## Artifact integrity and authenticity

Each published installer has a companion `StreamSnipAI-Setup.exe.sha256` file. A SHA-256 match detects accidental or malicious file changes relative to the checksum, but it does not establish the publisher's identity.

When SignPath signing is active, the release workflow checks the Authenticode signature status before publishing. Users can inspect a downloaded installer in PowerShell:

```powershell
Get-AuthenticodeSignature .\StreamSnipAI-Setup.exe |
    Format-List Status, StatusMessage, SignerCertificate
```

A valid SignPath Foundation signature identifies **SignPath Foundation** as the verified publisher. It does not identify Sifat Jaman as the certificate holder.

## Source and third-party components

The installer is built from this repository's own launcher, application source, assets, and installer scripts. The Windows setup process obtains runtime dependencies separately at installation time; the official installer does not claim ownership of those upstream projects. Optional hosted AI and publishing integrations are external services and are not part of the signed installer binary.

Only the project's own installer artifact is submitted for signing. The project will not submit unrelated third-party executables or binaries from another project as if they were its own.

## Attribution

When using a certificate provided by SignPath Foundation, the project will include the attribution requested by the Foundation:

> Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).
