# Code signing policy

This policy describes how official Windows installer releases for StreamSnip AI are built, reviewed, signed, and published.

## Scope and official downloads

This policy applies to the official StreamSnipAI-Setup.exe installer published in this repository's GitHub Releases. It does not claim that separately downloaded Python packages, FFmpeg, Whisper models, or other third-party components are signed by StreamSnip AI.

- Repository and project home: https://github.com/sifat-jaman-13/stream-clip-ai
- Official downloads: https://github.com/sifat-jaman-13/stream-clip-ai/releases
- Release source branch: master
- Build workflow: [Build and publish Windows release](.github/workflows/build-windows-release.yml)

## Project roles and release authority

StreamSnip AI is maintained by a single-person project team.

- **Author / committer:** [Sifat Jaman](https://github.com/sifat-jaman-13) — project owner, source-code maintainer, and author of changes made directly to the trusted master branch.
- **Reviewer:** Sifat Jaman — reviews and decides whether external contributor pull requests may be merged. The project does not currently have additional committer/reviewer members.
- **Release approver:** Sifat Jaman — reviews the proposed release commit, authorizes the release workflow, and is responsible for deciding whether the installer may be published and signed.

Contributors who do not have committer rights cannot directly modify the trusted release branch. Their proposed changes must be reviewed by the maintainer before merge. The maintainer is the only person authorized to dispatch the release workflow.

## Privacy and network behavior

**This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it.**

The app is local-first. Stream capture accesses the Twitch or YouTube URL selected by the user. Optional Gemini and Hugging Face providers receive transcript text only when the user selects and configures those services. Selected clips and captions are transferred to Zernio only when the user configures and uses publishing or enables auto-post. Package, FFmpeg, and speech-model downloads occur during explicit installation or first use. GitHub/PyPI update checks are user-initiated as documented in the README.

Relevant third-party services have their own privacy terms:

- [Google Privacy Policy](https://policies.google.com/privacy) — Gemini, when enabled by the user.
- [Hugging Face Privacy Policy](https://huggingface.co/privacy) — hosted inference, when enabled by the user.
- [Zernio Privacy Policy](https://zernio.com/privacy) — publishing, when configured and used.
- [Twitch Privacy Notice](https://www.twitch.tv/p/legal/privacy-notice/) — when the user selects a Twitch stream.
- [Google Privacy Policy](https://policies.google.com/privacy) — YouTube access and Google-hosted services.

The project does not include advertising, telemetry, or background collection of user media. Locally stored credentials, settings, recordings, and clips remain on the user's machine unless a corresponding external feature is deliberately used. See the README's [Data, credentials, and privacy](README.md#data-credentials-and-privacy) section.

## Build and signing procedure

1. Prepare a release-ready commit on the trusted/default master branch.
2. Review all changes since the previous release, including application source, dependencies, installer scripts, GitHub Actions workflows, and other build configuration. Build scripts and CI configuration are part of the source-code review.
3. Confirm that the version in pyproject.toml, autoclip.py, and installer/AutoClip.iss is identical.
4. Dispatch the Windows release workflow from master. The workflow rejects any other source ref and refuses to reuse an existing version tag.
5. The workflow runs on a GitHub-hosted Windows runner, executes the regression tests and Python syntax checks, installs a pinned Inno Setup compiler, and invokes the checked-in build_windows.ps1 script.
6. The resulting unsigned StreamSnipAI-Setup.exe is uploaded as a single-file GitHub Actions workflow artifact before the signing request is submitted.
7. SignPath verifies repository origin metadata (repository URL, master branch, commit ID, and GitHub workflow URL) using its predefined GitHub.com Trusted Build System. The SignPath project is configured for origin verification and a release policy that permits only the reviewed master branch.
8. The signed artifact is downloaded from SignPath. The workflow rejects the result unless Windows reports a valid Authenticode signature and the product name/version metadata still match the source release.
9. The workflow calculates SHA-256 from the signed installer and publishes the installer, checksum, and signer/build metadata in a GitHub Release. A failed signing request or invalid signature stops publication; there is no unsigned fallback.

The workflow derives the release tag from the version in source control. Existing version tags are never overwritten. Existing unsigned releases are not retroactively signed.

## SignPath project configuration

Before enabling the release workflow, the maintainer must:

1. Apply for the SignPath Foundation Open Source Code Signing program and obtain project approval.
2. Add the predefined **GitHub.com** Trusted Build System to the SignPath organization and link it to the StreamSnip AI SignPath project.
3. Install the SignPath GitHub App and grant it access to this repository, as required for source/build policies and origin verification.
4. Configure the project repository URL as https://github.com/sifat-jaman-13/stream-clip-ai.
5. Enable Trusted Build System verification and **Verify origin** for the release signing policy; restrict allowed branch names to master.
6. Configure the artifact configuration to accept a single Windows PE executable and enforce the product name StreamSnip AI and the release product version.
7. Create a signing-policy slug and an API token with submitter permission for that policy.
8. Enable repository GitHub Actions access to the settings below.

Required repository Actions settings:

| Type | Name | Value |
|---|---|---|
| Variable | SIGNPATH_ENABLED | true |
| Variable | SIGNPATH_ORGANIZATION_ID | SignPath organization ID |
| Variable | SIGNPATH_PROJECT_SLUG | SignPath project slug |
| Variable | SIGNPATH_SIGNING_POLICY_SLUG | SignPath release signing-policy slug |
| Secret | SIGNPATH_API_TOKEN | SignPath API token |

The release workflow deliberately fails before building/publishing when these settings are absent or incomplete. It does not create an unsigned release while signing is unavailable.

## Artifact identity and integrity

The Inno Setup installer embeds the following version-resource metadata, which is checked by the release workflow and must be enforced in the SignPath artifact configuration:

- Product name: StreamSnip AI
- Product version: the same semantic version recorded in all project version files
- File description: StreamSnip AI Setup

Each release contains:

- StreamSnipAI-Setup.exe — the signed installer.
- StreamSnipAI-Setup.exe.sha256 — SHA-256 checksum of the signed installer.
- SIGNATURE.txt — Authenticode status, signer subject, product/version, and source commit.

A SHA-256 match detects file changes relative to the published checksum; it does not prove publisher identity. Users can inspect the Authenticode signature in PowerShell:

```powershell
Get-AuthenticodeSignature .\StreamSnipAI-Setup.exe |
    Format-List Status, StatusMessage, SignerCertificate
```

When accepted into the SignPath Foundation program, the verified publisher is **SignPath Foundation**, not Sifat Jaman. The installer may separately display Sifat Jaman as its application publisher metadata; this does not change the certificate identity.

## Required attribution

For releases signed using the SignPath Foundation certificate:

> Free code signing provided by [SignPath.io](https://signpath.io), certificate by [SignPath Foundation](https://signpath.org).
