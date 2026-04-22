# Lip-Sync Studio — Brand & UI Brief

> A one-page brief to paste into Google Stitch (or any AI UI tool). Swap the
> working name "Lip-Sync Studio" freely — everything else is load-bearing.

---

## 1. Product in one line

Turn a script and a face photo into a lip-synced talking-head video, in any of
70+ Indic voices, in under a minute.

## 2. What the user does

1. Pastes a short script (1 sentence to ~2 minutes of speech).
2. Picks a voice (Indic languages — Hindi, Tamil, Bengali, etc. — plus named
   personas like "Aaradhya", "Rahul").
3. Uploads a face (JPG/PNG, or a short MP4 for more natural motion).
4. Clicks **Generate**. Watches a progress indicator (TTS → lip-sync → done).
5. Plays the result inline, downloads the MP4, or starts over.

That's the whole app. Every pixel should serve this flow.

## 3. Who it's for

- **Primary:** Indic-market creators, educators, marketers, solo founders who
  need talking-head video without a studio, camera, or on-screen talent.
- **Secondary:** Product teams prototyping avatars, announcements, training
  content, localized explainers.
- **Literacy:** comfortable with consumer web apps (Notion, Canva, ChatGPT),
  not necessarily technical. They expect defaults that just work.

## 4. Brand personality

| Is                                   | Is not                              |
| ------------------------------------ | ----------------------------------- |
| Quiet, confident, studio-grade       | Loud, gamer, neon                   |
| Indic-first, quietly multilingual    | Western-default, English-only vibe  |
| Creative-tool precise (Figma/Linear) | Enterprise-dashboard heavy          |
| Fast and opinionated                 | Configuration-knob-for-everything   |

Tone in copy: direct, verb-first, no exclamation marks. "Generate video" beats
"Let's create something amazing!". Microcopy is warm but terse — one short
sentence max per state.

## 5. Visual direction

### Palette
Dark-first, photo/video-forward. The generated video is the hero — chrome
should recede.

- **Surface 0 (bg):** near-black, slightly warm — `#0E0F13`
- **Surface 1 (cards):** `#16181F`
- **Surface 2 (inputs/hover):** `#1F222B`
- **Text primary:** `#EDEEF2`
- **Text muted:** `#8A8F9B`
- **Accent (primary CTA, progress):** warm saffron / amber — `#F59E0B` or a
  brand-calibrated `#E8A33D`. Pulls from Indic textile palettes without being
  on-the-nose.
- **Accent on dark (secondary highlight):** a muted teal — `#4FB3A9` — for
  success/"done" states.
- **Destructive / error:** `#E26D5A` (terracotta, not pure red).

A light-mode variant is nice-to-have, not required for v1.

### Typography
- **Display / H1:** Inter Tight or Geist, tight tracking, 36–48px.
- **Body / UI:** Inter, 15–16px body, 13px for secondary.
- **Script/text input:** tabular digits, comfortable line-height (1.55).
- **Indic support:** the font stack must render Devanagari, Tamil, Bengali,
  Telugu, Kannada, Malayalam, Gujarati, Punjabi gracefully. Use Noto Sans for
  the language-tag pills inside the voice picker.

### Shape & spacing
- 12px border radius on cards, 8px on inputs/buttons.
- Generous padding (24–32px inside cards). The app has one job — don't crowd.
- 1px hairline borders at `rgba(255,255,255,0.06)`. No heavy shadows.

### Motion
- 150–200ms ease-out for hovers and state changes.
- Progress bar: smooth, never jumpy. When TTS finishes and lip-sync starts, the
  bar should glide forward, not snap.
- Subtle shimmer on the video-preview placeholder while rendering — not a
  spinner.

### Iconography
- Lucide or Phosphor, 1.5px stroke, rounded. Never filled/heavy.

## 6. Key screens

### A. **Home / compose** (the only real screen)
Single-column, max-width ~720px, centered. Card contains, top-to-bottom:
1. **Script textarea** — multiline, auto-growing, monospace-hint placeholder
   in local script if the selected voice is Indic ("अपनी स्क्रिप्ट यहाँ लिखें…").
   Character / approximate-seconds counter bottom-right.
2. **Voice picker** — combobox with search. Grouped by language. Each row:
   voice name, language pill, gender glyph. The v2 named voices (Aaradhya,
   Rahul, etc.) get a subtle "Premium" tag.
3. **Face upload** — large drag-and-drop zone. Shows a thumbnail preview the
   moment a file is selected, with file name + duration (for MP4).
4. **Advanced** — collapsed accordion labeled "Advanced". Inside: JSON textarea
   for params. Default to collapsed; 95% of users never open it.
5. **Generate** button — full-width primary on mobile, right-aligned on desktop.

Top-right of the page, persistent: tiny muted line showing active models
(`svara-tts-v1 + musetalk-v1.5`). No settings menu, no nav, no sidebar in v1.

### B. **Job-in-progress** (replaces the form when submitting)
Same card shell. Inside:
- Stage label: "Generating audio…" → "Generating video…" → "Done".
- Horizontal progress bar (not circular). Warm-amber fill on dark track.
- Muted job-id below ("job 7a3f…e102") for support/debugging.
- **Cancel / start over** as a ghost button in the corner — low-emphasis but
  always reachable.

### C. **Done**
- Video player (native HTML5 controls, `autoPlay`, `playsInline`). No custom
  chrome.
- Two actions below: **Download MP4** (primary), **New video** (ghost).
- Optional: a "Play TTS audio only" link, tiny, muted, for verifying voice
  quality independent of the lip-sync.

### D. **Failed**
- Same card. Terracotta error banner at top with the error detail.
- Actions: **Try again** (primary, returns to form with values preserved),
  **Start over** (ghost, clears form).
- Never blame the user. "Lip-sync service is temporarily unavailable." — not
  "Invalid request."

## 7. States to design (don't skip)

- **Empty / first-load** — voices still loading (skeleton on the picker, not a
  spinner blocking the form).
- **Voices failed to load** — inline banner, "Retry" button, form stays usable
  with a disabled voice picker.
- **Textarea long-script warning** — soft hint above ~1000 chars: "long scripts
  take longer to render".
- **Upload validation** — wrong file type, too large (>50MB), unreadable video.
  Inline under the upload zone, never a modal.
- **Network offline** — banner at top of page, dismissible.
- **Mobile** — everything stacks, upload zone becomes a full-width button,
  textarea fills viewport on focus.

## 8. Accessibility

- WCAG AA contrast on the dark palette. Verify amber-on-black at 4.5:1 for
  body text, 3:1 for large/UI.
- Every icon has a label. Every input has a persistent label (not just
  placeholder).
- Keyboard: tab order matches visual order, Enter submits from textarea only
  with Cmd/Ctrl+Enter (so line breaks remain natural).
- Screen-reader live region announces stage transitions ("Audio generated.
  Generating video.") and completion.
- Indic-language scripts must render at the correct size — don't let a fallback
  font shrink Devanagari characters relative to Latin.

## 9. What NOT to design

- No dashboard, no job history list, no user accounts, no billing, no team
  workspace. (The app is a single-shot tool today.)
- No chat UI, no avatar gallery, no template picker.
- No hero illustration or marketing copy on the app surface. The product page
  sells; the app just works.
- No dark-pattern "upgrade" nags.

## 10. Inspiration anchors

- **Linear** — density, microcopy discipline, hairline borders.
- **Figma file dialog** — upload-zone pattern.
- **OpenAI Playground (pre-2024)** — single-column creator tool feel.
- **Vercel dashboard dark** — palette warmth on near-black.
- **Notion AI inline** — calm progress affordances.

Avoid: generic SaaS purple, glassmorphism, AI-gradient blobs, Stable-Diffusion-
style marketing visuals.

---

## Pasting into Stitch

If you want a one-shot prompt for Stitch, start with:

> Design a single-page creator tool called "Lip-Sync Studio". It turns a
> written script + an uploaded face photo into a lip-synced talking-head video
> using Indic-language voices (Hindi, Tamil, Bengali, Telugu, and 20+ more,
> plus named personas like "Aaradhya" and "Rahul"). The only screen is a
> centered card (max 720px wide) with: script textarea, voice combobox grouped
> by language, face upload (drag-drop with thumbnail preview), collapsed
> "Advanced" accordion, and a full-width "Generate" button. After submit,
> the card becomes a stage-by-stage progress view ("Generating audio" →
> "Generating video" → "Done"), then reveals a native video player with
> Download MP4 + New Video actions. Dark-first, near-black surfaces, warm
> saffron-amber accent (#F59E0B), muted teal success (#4FB3A9), terracotta
> error (#E26D5A). Inter / Inter Tight typography with proper Devanagari +
> Tamil + Bengali rendering. 12px card radius, hairline borders, no heavy
> shadows. Calm, studio-grade, Linear-meets-Figma feel. Cover states: loading
> voices, failed to load voices, upload validation, long-script warning,
> running, done, failed, mobile.
