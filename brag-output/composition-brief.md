# Hyperframes Composition Brief: Saarthi

## Objective
Create a short launch-style brag video for Saarthi, a local-first AI money guy for the whole family.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: ~20.5 seconds

## Source Material
- Project root: /Users/vedantshah/Desktop/family_finance_advisor
- Primary files read: README.md, frontend/DESIGN.md, frontend/src/index.css
- Product name: Saarthi
- Tagline / strongest claim: "Rich families always have a money guy. What if yours did too?"
- Key UI or visual moment to recreate: the texting-style chat (iMessage-blue outgoing bubbles, dark incoming bubbles, bouncing typing dots) on the warm-dark surface, answering the maturing-FD question from the README's "See it in action".
- Copy that must appear verbatim:
  - "Rich families always have a money guy."
  - "What if yours did too?"
  - "Mom's 5L FD matures next month. Where should she park it?"
  - "Mom's 4 years from retirement, so this money shouldn't take equity risk."
  - "Top up the emergency fund first, then ladder the rest in a short-term debt fund."
  - "You hold the reins."

## Creative Direction
- Tone preset: polished
- Creative direction: quiet, premium product film for a family money guy
- Interpretation: fewer scenes, longer holds, confident restraint; warm and calm, never loud or salesy; the chat is the emotional center and breathes.
- Angle: Rich families have always had one trusted person who knows everyone's money and gives the honest tradeoff. Saarthi is that person for everyone else, on your own machine. Sell the feeling, then prove it with one real conversation.
- Hook: "Rich families always have a money guy." then "What if yours did too?"
- Outro / punchline: the wordmark with "You hold the reins." and a local-first tag.
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - Unrelated visual redesign
  - Em dashes anywhere in on-screen copy (project rule)

## Visual Identity
- Background: oklch(13% 0.012 55) warm charcoal
- Text: oklch(95% 0.012 75) off-white; muted oklch(63% 0.02 70)
- Accent: mint oklch(85% 0.08 160); outgoing bubble iMessage blue oklch(63% 0.19 254); incoming bubble oklch(22% 0.012 55)
- Display font: Outfit (Google Fonts), 600-700 tracking-tight
- Body font: Outfit 400-500
- Visual references from the project: warm-dark lamplit surface, iMessage-style chat bubbles, bouncing typing dots, mint accent for primary, tabular numerals.

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. Hook — 4.2s — "Rich families always have a money guy." then "What if yours did too?"
2. Wordmark reveal — 2.1s — "Saarthi" + "A money guy for your whole family. On your own machine."
3. The conversation (centerpiece) — 8.7s — outgoing FD question, typing dots, two teaching reply bubbles.
4. What makes it different — 3.0s — "Knows every family member." / "Teaches, never sells." / "Your data never leaves home."
5. Outro — 2.5s — "Saarthi" wordmark, "You hold the reins.", local-first tag.

## Audio
- Audio role: warm, restrained business bed
- Audio arc: low warm bed runs throughout; soft swish on the hook-turn; quiet message pop on each chat bubble on the beat; light ticks on the differentiator lines; soft chime on the outro wordmark as music fades to silence.
- Music: happy-beats-business-moves-vol-9-by-ende-dot-app.mp3
- Music treatment: start at 0, volume ~0.55, fade out over the final ~1.2s under the outro.
- Music cue guidance: bundled preset read. Strong cues: 4.23s (hook to reveal), 6.34s (user bubble), 10.54s and 12.65s (reply bubbles). Beat grid ~0.52s apart for the three differentiator lines at ~15.28 / 15.81 / 16.34s.
- Audio-reactive treatment: none. Extraction helper (ships with hyperframes/GSAP skills) is not installed here; rely on beat-locked timing. Documented, not blocking.
- Audio-coupled moments:
  - Scene 1 hook-turn — soft transition swish
  - Scene 3 each bubble — soft message pop, on the beat
  - Scene 3 typing dots — faint key ticks
  - Scene 4 lines — subtle ticks
  - Scene 5 wordmark — soft confirm chime
- SFX selection guidance: prefer soft, low-high-frequency pops and ticks; one sound per moment; never stack. Choose exact files from the brag SFX library after the animation exists.
- Exact SFX choice: pick filenames, timestamps, density, and volume to match the implemented animation.
- Audio files: copy chosen music and SFX into `brag-output/composition/assets/`.

## Hyperframes Instructions
Use the current hyperframes CLI workflow (`lint` / `validate` / `inspect` / `render`). Single self-contained `index.html` root composition with one paused root timeline registered on `window.__timelines`. Every timed element carries `class="clip"` + `data-start` + `data-duration` + `data-track-index`. Deterministic only (no Date.now, no Math.random, no network beyond CDN script + Google Font). Show the real chat UI. Keep all on-screen copy readable (hold each line to its reading floor). Beat-lock the major bubble reveals to the vol-9 strong cues. Run lint and validate before render.
