# Local browser-assisted publishing

StreamSnip AI supports a separate manual browser-preparation route alongside optional Zernio publishing. The manual route uses Playwright and a dedicated persistent profile for Chrome, Edge, or Firefox. It does not reuse or take over the user's everyday browser profile.

## Setup

1. Install project dependencies with `python -m pip install -r requirements.txt`.
2. For Firefox, install the Playwright Firefox runtime once with `python -m playwright install firefox`. Chrome and Edge use their installed stable browser channels.
3. Open Publish, choose one manual platform, select the browser, and press Post.
4. Sign in to the social account in the StreamSnip AI browser profile the first time. Later sessions reuse that profile.

## Safety and current behavior

- The local backend resolves the clip path from the app's clip library; the browser does not receive an arbitrary filesystem path from the page.
- The browser selects the local clip when the platform exposes a file input and fills title/description fields when matching visible fields are found.
- Platform upload pages change frequently. If an upload input or metadata field is not detected, complete that field manually in the opened browser page.
- StreamSnip AI never clicks the final Publish/Post button. Review the preview, destination, visibility, title, description, and tags before publishing.
- Prepare one manual platform at a time in the current UI. Zernio's automated queue remains a separate integration and is not required for manual posting.
- Browser work is serialized on a dedicated worker thread because the local HTTP server handles requests concurrently and Playwright contexts are thread-affine.

## API

- `GET /api/browser/status` reports the selected browser/profile state.
- `POST /api/browser/prepare` accepts a clip library name, platform, title, description, and browser choice. The local session token is required.
- `POST /api/browser/close` closes the dedicated browser context. The local session token is required.

This is a browser-assisted preparation workflow, not unattended publishing. Site-specific upload selectors must be regression-tested whenever a platform changes its composer UI.
