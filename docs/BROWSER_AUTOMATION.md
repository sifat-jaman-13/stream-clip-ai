# Manual posting in your default browser

StreamSnip AI opens social upload pages in the operating system's normal default browser. It does not launch Playwright, create or manage browser profiles, read browser cookies, or try to take over an existing browser session.

## How it works

1. Open Publish and select one manual platform.
2. Press Post. StreamSnip opens that platform's upload page through Windows' default URL handler. Your existing browser profile and login remain in use.
3. Select the clip file on the platform's upload page.
4. Use Copy title and Copy caption in StreamSnip to paste the saved post text into the platform.
5. Review the video, account, visibility, title, description, and tags. Click Publish yourself.

Manual posting does not require Playwright, a browser extension, a separate sign-in, or a StreamSnip browser profile. It does require selecting the video and pasting the text manually because StreamSnip intentionally does not automate or control the user's everyday browser.

## Safety and behavior

- The local backend resolves the clip path from the app's clip library before opening the platform URL.
- Browser selection is not configurable: manual posting always uses the system default browser.
- No dedicated browser profile directory is created or maintained.
- StreamSnip AI never clicks the final Publish/Post button.
- Zernio remains a separate optional automated publishing integration.

## API

- `GET /api/browser/status` reports the system-default browser mode and explicitly reports `dedicated_profile: false`.
- `POST /api/browser/prepare` accepts a clip library name, platform, title, and description. A legacy browser field is ignored for compatibility.
- `POST /api/browser/close` clears the last preparation status; it does not close the user's browser.
