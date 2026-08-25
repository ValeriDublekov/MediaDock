# Gemini API Model IDs

Reviewed: 2026-08-25

This is the repository reference for Gemini-branded model IDs listed in the
Google Gemini API catalog. Model availability is project-, region-, quota-, and
API-version-dependent. The authoritative runtime check is the Gemini API
`models.list` endpoint, filtered to models that support `generateContent`.

Official sources:

- [Gemini API models](https://ai.google.dev/gemini-api/docs/models)
- [Gemini API model deprecations](https://ai.google.dev/gemini-api/docs/deprecations)
- [Models API](https://ai.google.dev/api/models)
- [Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)

## MediaDock text and JSON candidates

These are the relevant candidates for `AiMatcher`, which sends text prompts and
expects JSON structured output. The current code must still verify the selected
model's supported actions and generation configuration before production use.

| Model ID | Lifecycle | MediaDock guidance |
| --- | --- | --- |
| `gemini-3.7-flash` | Stable | Preferred quality candidate; migrate the current generation payload first. |
| `gemini-3.6-flash` | Stable | Strong general candidate; use the Gemini 3 generation configuration. |
| `gemini-3.5-flash` | Stable | General text/multimodal candidate. |
| `gemini-3.5-flash-lite` | Stable | Cost and latency candidate. |
| `gemini-3.1-flash-lite` | Stable | Current MediaDock default until a newer model passes compatibility tests. |
| `gemini-2.5-flash` | Stable | Valid fallback; do not mark it as legacy or remap it automatically. |
| `gemini-2.5-flash-lite` | Stable | Valid lower-cost fallback; do not mark it as legacy or remap it automatically. |
| `gemini-2.5-pro` | Stable | Quality candidate for offline or low-volume repair work. |
| `gemini-3.1-pro-preview` | Preview | High-quality candidate; preview lifecycle and cost apply. |
| `gemini-3-flash-preview` | Preview | Preview candidate; do not use as an unreviewed production default. |

## All currently listed Gemini-family and managed Gemini IDs

### Stable

- `gemini-3.7-flash`
- `gemini-3.6-flash`
- `gemini-3.5-flash`
- `gemini-3.5-flash-lite`
- `gemini-3.1-flash-lite`
- `gemini-3.1-flash-image`
- `gemini-3.1-flash-lite-image`
- `gemini-3-pro-image`
- `gemini-2.5-flash`
- `gemini-2.5-flash-image`
- `gemini-2.5-flash-lite`
- `gemini-2.5-pro`
- `gemini-embedding-001`

### Preview or experimental

- `gemini-3.1-pro-preview`
- `gemini-3-flash-preview`
- `gemini-3.5-live-translate-preview`
- `gemini-3.1-flash-live-preview`
- `gemini-3.1-flash-tts-preview`
- `gemini-omni-flash`
- `gemini-2.5-flash-native-audio-preview-12-2025`
- `gemini-2.5-flash-preview-tts`
- `gemini-2.5-pro-preview-tts`
- `gemini-2.5-computer-use-preview-10-2025`
- `gemini-embedding-2-preview`
- `gemini-robotics-er-2-preview`
- `gemini-robotics-er-1.6-preview`
- `deep-research-preview-04-2026`
- `deep-research-max-preview-04-2026`
- `antigravity-preview-05-2026`

## Specialized IDs

The following IDs are valid Gemini-branded API models but are not drop-in
replacements for MediaDock's text/JSON matcher:

| Model ID | Intended use |
| --- | --- |
| `gemini-3.1-flash-image` | Image generation and editing. |
| `gemini-3.1-flash-lite-image` | Lower-cost image generation and editing. |
| `gemini-3-pro-image` | Image generation and editing. |
| `gemini-2.5-flash-image` | Image generation and editing. |
| `gemini-3.5-live-translate-preview` | Live speech translation. |
| `gemini-3.1-flash-live-preview` | Live audio/video interaction. |
| `gemini-3.1-flash-tts-preview` | Text to speech. |
| `gemini-2.5-flash-native-audio-preview-12-2025` | Native-audio Live API. |
| `gemini-2.5-flash-preview-tts` | Text to speech. |
| `gemini-2.5-pro-preview-tts` | Text to speech. |
| `gemini-2.5-computer-use-preview-10-2025` | Computer-use interaction. |
| `gemini-embedding-001` | Text embeddings. |
| `gemini-embedding-2-preview` | Multimodal embeddings. |
| `gemini-robotics-er-2-preview` | Robotics. |
| `gemini-robotics-er-1.6-preview` | Robotics. |
| `deep-research-preview-04-2026` | Managed deep-research agent. |
| `deep-research-max-preview-04-2026` | Managed deep-research agent with maximum comprehensiveness. |
| `antigravity-preview-05-2026` | Managed coding/agent environment. |

Image, audio, Live API, embedding, robotics, and computer-use models require a
different request contract or API flow. Do not place them in `GEMINI_MODEL` for
`AiMatcher` without a dedicated adapter and tests.

Deep Research and Antigravity are managed agent products, not drop-in
`generateContent` model IDs for this backend. Keep them out of `GEMINI_MODEL`.

## Current MediaDock compatibility notes

- The current default is `gemini-3.1-flash-lite` in
  `backend/src/movies_feed/ai_matcher.py`.
- The current client preserves the configured model ID and sends `temperature` and the legacy
  `thinkingConfig.thinkingBudget` field. Gemini 3.6 and 3.7 migration guidance
  requires reviewing these settings; do not switch the default by changing one
  string only.
- `gemini-2.5-flash` and `gemini-2.5-flash-lite` are currently valid stable IDs.
  The client does not remap these IDs; startup capability validation decides
  whether the selected model supports `generateContent`.
- The `confidence` field is an application contract. A model being listed by
  the API does not make its output semantically safe for catalog mutations.
- Stable model IDs are preferable for repeatable production behavior. Preview
  and latest aliases may change behavior or lifecycle without a code change.

## Latest aliases

The official model documentation defines a `latest` naming pattern and gives
`gemini-flash-latest` as a valid example. Such aliases are intentionally not
part of the stable MediaDock default because Google may hot-swap their target.
Use an alias only after the runtime capability check and compatibility tests
pass for the active project.

- `gemini-flash-latest` (documented latest Flash alias)

The documentation does not provide a permanent exhaustive list of every
possible alias. Query `models.list` before using any additional `latest` or
experimental name.

## Runtime discovery

Do not treat this file as a permanent allowlist. Before enabling a model, query
`models.list` and require `generateContent` support. A REST request should use an
`x-goog-api-key` header; do not put the API key in a URL or log it.

The exact response from `models.list` is the final authority for the active
project. The CLI validates the configured model against that response for AI
modes and requires `generateContent`. Update this file when the official
catalog changes, and record the review date and any deprecation replacement.

## Not active

The following IDs are shown in the deprecation catalog as shut down by the
review date and must not be selected:

- `gemini-2.0-flash`
- `gemini-2.0-flash-001`
- `gemini-2.0-flash-lite`
- `gemini-2.0-flash-lite-001`
- `gemini-3.1-flash-lite-preview`
- `gemini-3.1-flash-image-preview`
- `gemini-3-pro-preview`
- `gemini-3-pro-image-preview`

The official deprecation page is the source for shutdown dates and migration
targets. Do not infer validity from a model's marketing name alone.

The model catalog also lists separate non-Gemini families such as Imagen, Veo,
and Lyria. They are intentionally outside this Gemini-family reference because
they use different media-generation APIs and are not valid `AiMatcher` choices.

The model catalog also lists separate non-Gemini families such as Imagen, Veo,
and Lyria. They are intentionally outside this Gemini-family reference because
they use different media-generation APIs and are not valid `AiMatcher` choices.
