# Product

## Platform

Desktop-hosted local web application. The primary supported workflow is Windows.

## Users

Primary user: an individual creator or clip editor using a desktop PC to monitor stream sources, capture live content, process recorded VODs, review generated clips, and prepare short-form posts.

## Product purpose

StreamSnip AI is a local-first creator clipping workspace. It brings source selection, live capture, creator monitoring, transcription, AI-assisted highlight analysis, clip rendering, review, and publishing handoff into one application. Success means moving from a live moment or recorded VOD to a reviewed clip while retaining control over capture and the final publishing action.

## Positioning

A desktop media workflow that connects stream capture and creator monitoring to transcription, highlight selection, captioned clip rendering, and publishing preparation. The application runs locally and uses hosted services only when the user selects and configures them.

## Operating context

The React and TypeScript Creator Studio runs in the local browser. The Python application owns capture and media processing and exposes application services through a loopback-only FastAPI transport. The user can run a built dashboard or use Vite during development.

Manual publishing opens the platform in the operating system's default browser. The user selects the local video and completes the final Publish action. Direct publishing uses a configured Zernio integration and connected social accounts.

## Capabilities and constraints

- The application includes Dashboard, Live Studio, Creators, Clip library, Published, Hype words, Publishing, Settings, Activity, Help, and About.
- Live Studio groups Capture, AI provider, Transcription, and Captions into pre-capture setup tabs.
- Capture never begins automatically when a page opens; it requires an explicit user action.
- Creator profiles support independent live monitoring and recorded-VOD folder watching.
- Hosted AI providers receive transcript text when selected. Local Hook Words scoring and a local Ollama instance are alternatives.
- Provider availability, connected social accounts, and publishing outcomes depend on external configuration and responses.
- The local API should remain bound to loopback and must not be exposed to a LAN or the public internet.
- Preserve application API contracts, user data, credentials, and operational behavior when changing the frontend.
- Do not invent engine state, processing progress, clip content, provider success, or posting status.

## Brand and appearance

- Product name: StreamSnip AI.
- The default visual system is the Odysseus graphite theme with cyan information accents and coral actions.
- Available appearance themes: Odysseus, Studio Light, Studio Dark, GitHub Dark, Nord, and Odysseus Paper.
- JetBrains Mono is the default application font. Google Sans, Inter, Roboto, Open Sans, Montserrat, Poppins, Lato, Nunito Sans, DM Sans, IBM Plex Sans, Space Grotesk, and Fira Code are selectable alternatives.
- The interface is an original creator workspace informed by familiar creator-studio patterns. It is not a pixel copy of another product.

## Product principles

- Keep capture state and destructive actions explicit and understandable.
- Make the journey from source to reviewed clip direct and predictable.
- Preserve user control over monitoring, recording, and publishing.
- Surface real engine state and actionable errors rather than decorative metrics.
- Keep the workspace responsive and usable during long-running local processing.
- Explain when transcript text is sent to a hosted AI provider.

## Accessibility

Use semantic controls, visible keyboard focus, sufficient contrast, labelled inputs, keyboard-operable tabs, and reduced-motion support. Status must be conveyed through text or icons as well as color.
