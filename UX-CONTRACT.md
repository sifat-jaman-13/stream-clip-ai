# StreamSnip AI UX Contract

## Scope

This contract governs the main Creator Studio workflow and the app-wide Settings route. Its purpose is to keep pre-capture controls discoverable and prevent capture from starting with a different configuration than the one visible to the user.

## Canonical locations

| User intent | Canonical location |
|---|---|
| Choose Twitch/YouTube stream or local VOD | Live Studio - Source panel |
| Configure capture chunks, scoring, bitrate | Live Studio - Capture tab |
| Select AI provider and manage API keys | Live Studio - AI provider tab |
| Choose transcription model and language | Live Studio - Transcription tab |
| Configure framing, subtitle style, creator credit, profanity filter | Live Studio - Captions tab |
| Configure storage folders and application housekeeping | Settings - General |
| Choose theme and application font | Settings - Appearance / top-bar Appearance control |

Capture, AI provider, Transcription, and Captions are not global Settings sections. They remain visible in the Studio setup tab bar before the Start capture action.

## Live Studio sequence

1. Choose Live stream or Video file / VOD.
2. Enter or browse for the source.
3. Show a detected creator handle when the URL exposes one.
4. Review the four configuration tabs.
5. Save current capture and AI settings.
6. Start capture only after an explicit user action.

Opening Live Studio never starts a recording. The Start capture action is below the setup tabs and stays visible while the page scrolls.

## Source and creator identity

The source mode and source URL in Live Studio are canonical. Caption framing preview consumes that same source; it must not expose a second editable source URL.

Supported creator-handle inference:
- Twitch channel URLs such as twitch.tv/<handle>.
- YouTube handle URLs such as youtube.com/@<handle>.
- YouTube custom and legacy user URLs such as /c/<name> and /user/<name>.

A YouTube watch, shorts, or short-link URL does not encode a channel display name. In that case the UI must not invent one; it explains that a manual creator credit can be entered in Captions.

The streamer_tag value is a manual override. When it is empty, the engine infers the handle from the source URL. When a user clears the override, automatic detection resumes. The same resolution rule is used for on-screen creator credit and clip metadata.

Creator monitor forms auto-fill the creator name from supported channel URLs until the user edits the name manually. Manual names are never overwritten by later URL edits.

## AI provider defaults and credentials

- Gemini is the default only when there is no saved provider configuration.
- An explicit saved provider is preserved; a default change must not overwrite a user's choice.
- A Gemini API key is stored locally and is never returned to the frontend.
- The AI tab discloses that transcript text is sent to Google Gemini for highlight analysis and that API usage consumes the user's Google quota.
- If Gemini is selected and no saved key exists, Start capture moves focus to the AI provider tab and explains the required setup.
- API key entry is not complete until the user presses Save AI settings.

## Save and failure behavior

- Capture and transcription fields save automatically and show a saving/saved/error status.
- Caption options save automatically.
- Provider/model selection and credentials use the explicit AI Save action.
- Before Start capture, pending capture settings are flushed to the local API and AI settings are saved. A save failure prevents the start request and is explained in the UI.
- A failed source preview must leave the selected source and settings intact.
- Start and Stop are explicit actions; duplicate starts are disabled while a request is pending.
- Errors are shown near the affected flow or through the shared toast region, never only in the browser console.

## Keyboard and responsive behavior

- Studio tabs expose tablist, tab, and tabpanel semantics and support Left/Right Arrow navigation.
- All inputs have visible labels and focus treatment.
- At narrow widths, the setup tabs scroll horizontally and session status stacks below the editor.
- The capture action bar wraps into a vertical layout on small screens.
- Reduced-motion preferences are respected.
