# Brag Plan: Saarthi

## What is this app?
A local-first AI "money guy" for your whole family. It runs on your own machine, knows every family member as a distinct person, and teaches you the tradeoff behind each money decision instead of selling you a product.

## The angle
Rich families have always had a quiet advantage: one trusted person who knows everyone's money and tells you the honest tradeoff. Saarthi is that person, for everyone else, running on a machine in your own home. The video sells the *feeling* of having a wise family advisor on call, then proves it with one real conversation: a maturing fixed deposit, answered with knowledge of Mom's age, her retirement runway, and the family's thin emergency fund. Not a chatbot. A money guy who already knows your family.

## Hook (first 2-3 seconds)
The README's actual headline, in big warm type on a dark, lamplit screen:
"Rich families always have a money guy." then a beat, then "What if yours did too?"
The line earns the next twenty seconds because it names a real, slightly unfair advantage and offers it to you.

## Key moments (the middle)
- The Saarthi wordmark resolving on warm charcoal, with the one line: "A money guy for your whole family. On your own machine."
- The real product: a texting-style chat. A blue user bubble asks about Mom's maturing FD. Typing dots. Then Saarthi's reply arrives as two calm bubbles that *teach* the tradeoff and clearly already know Mom is near retirement.
- Three quiet differentiators landing one by one: "Knows every member." / "Teaches, never sells." / "Your data never leaves home."

## Outro / punchline
The wordmark again, with the charioteer line that gives the product its name: "You hold the reins." plus the quiet tag: local-first, no cloud, no database.

## User flow worth showing
The product *in use* is a conversation. Entry: a real family money question typed as a chat bubble. Key action: Saarthi thinks (typing dots), then replies. Result: two short bubbles that explain *why*, grounded in the family's actual situation. This recreates the README "See it in action" maturing-FD example in the app's real iMessage-style chat UI (warm-dark surface, blue outgoing bubbles, dark incoming bubbles, bouncing typing dots).

## Tone
- Preset: polished
- Creative direction: a quiet, premium product film for a family money guy
- Interpretation: fewer scenes, longer holds, confident restraint. Warm and calm, never loud or salesy. Motion is smooth and slow-settling; the chat is the emotional center and is allowed to breathe.

## Format: landscape — 1920x1080
## Duration: 20.5 seconds

## Visual identity (from the project)
- Background: oklch(13% 0.012 55) warm charcoal, never pure black
- Surface (bubbles, cards): oklch(17.5% 0.014 55) / incoming bubble oklch(22% 0.012 55)
- Accent: mint oklch(85% 0.08 160); outgoing chat bubble iMessage blue oklch(63% 0.19 254)
- Text: oklch(95% 0.012 75) warm off-white; muted oklch(63% 0.02 70)
- Display + body font: Outfit (Outfit Variable in-app; Outfit via Google Fonts in the composition)
- Strongest visual element: the texting-style chat with iMessage-blue outgoing bubbles, dark incoming bubbles, and bouncing typing dots, on the warm-dark lamplit surface.

## Share copy (draft)
Rich families always have a money guy. I built one that runs on your own machine and knows your whole family. Saarthi teaches you the tradeoff instead of selling you a product, and your financial data never leaves home.

## Audio direction
- Role: warm bed, polished and restrained
- Music: happy-beats-business-moves-vol-9-by-ende-dot-app.mp3 (114.8 BPM, warm business mood, clean intro)
- Music treatment: start at 0 around volume 0.55, gentle fade-out over the final 1.2s under the outro
- Music cue guidance: preset cues read from the bundled vol-9 cue file. Strong cues to target: 4.23s (hook to reveal), 6.34s (user message slams in), 10.54s and 12.65s (the two reply bubbles land). Beat grid ~0.52s apart for the differentiator lines around 15.3-16.4s.
- Audio-reactive treatment: none planned. The HyperFrames audio-reactive extraction helper ships with the hyperframes/GSAP skills, which are not installed in this environment; rely on beat-locked timing instead. Documented, not blocking.
- SFX posture: sparse, motion-matched. A soft transition swish on hook-to-reveal, a gentle message pop on each chat bubble, a faint key tick under the typing dots, a soft confirm chime on the outro wordmark.
- Audio-coupled moments: each chat bubble arrival (pop, on the beat), the typing dots (faint key ticks), the differentiator lines (subtle ticks), the outro wordmark (soft chime).
- Restraint rule: audio must never get busy or salesy. No risers, no stingers stacked together, no pulsing. One sound per moment, quiet.

## Storyboard

### Scene 1 — Hook — 4.2s
Warm charcoal screen. Large Outfit display type. "Rich families always have a money guy." fades/slides up and settles (hold ~1.8s). Then on a beat, "What if yours did too?" appears beneath in mint. Hold so both read.
Sequential/interaction: yes — two lines appear in sequence, the second on the 4.23s strong cue as the scene exits.
Audio intent: warm bed establishes; a soft swish marks the turn into the reveal.
Audio-coupled idea: subtle transition swish at the line-2 reveal / scene exit.
Music: warm, low, building gently.
Transition mood: soft → Scene 2

### Scene 2 — Wordmark reveal — 2.1s
"Saarthi" wordmark resolves center on warm charcoal (Outfit, tracking-tight), with a thin mint underline drawing in. Subline: "A money guy for your whole family. On your own machine."
Sequential/interaction: none (one clean reveal).
Audio intent: settle, a held warm chord under the name.
Audio-coupled idea: none, keep it clean.
Music: warm, present.
Transition mood: soft crossfade → Scene 3 (the user bubble slams in on 6.34s)

### Scene 3 — The conversation (centerpiece) — 8.7s
A phone-style chat column on the warm-dark surface. A blue outgoing bubble slides in from the right (beat-locked 6.34s): "Mom's 5L FD matures next month. Where should she park it?" Hold so it reads. Three bouncing typing dots appear in a dark incoming bubble (~8.0s). Then two incoming dark bubbles arrive one by one and hold:
Bubble 1 (beat-locked 10.54s): "Mom's 4 years from retirement, so this money shouldn't take equity risk."
Bubble 2 (beat-locked 12.65s): "Top up the emergency fund first, then ladder the rest in a short-term debt fund."
Both reply bubbles stay fully on screen together until ~15.0s so they are readable.
Sequential/interaction: yes — outgoing bubble, then typing dots, then two incoming bubbles one by one, each with a soft message pop. Simulated real texting.
Audio intent: the heart of the film; each bubble is a small, satisfying arrival.
Audio-coupled idea: message pop on each of the three bubbles; faint key ticks under the typing dots.
Music: warm, steady, supportive.
Transition mood: clean → Scene 4

### Scene 4 — What makes it different — 3.0s
Three short lines appear quickly in sequence on warm charcoal, each with a small mint dot, then the full set holds:
"Knows every family member." / "Teaches, never sells." / "Your data never leaves home."
Sequential/interaction: yes — three lines reveal on consecutive beats (~15.28, 15.81, 16.34s) then the whole set holds to ~18.0s for reading.
Audio intent: three light, confident ticks; momentum without noise.
Audio-coupled idea: subtle tick on each line; non-text dots may hit the beat.
Music: warm, lifting slightly.
Transition mood: soft → Scene 5

### Scene 5 — Outro — 2.5s
"Saarthi" wordmark center with a soft mint glow. The line "You hold the reins." settles beneath it. A small bottom tag: "local-first · no cloud · no database". Music fades out under it; a soft confirm chime rings on the wordmark.
Sequential/interaction: none — one calm landing.
Audio intent: resolve and exhale; let the chime ring as music fades.
Audio-coupled idea: soft confirm chime on the wordmark settle.
Music: warm bed fading to silence over ~1.2s.
Transition mood: hold to black.

**Music mood for this video:** polished (warm business bed, restrained)
**Audio summary:** A warm, low business bed runs the whole film; the hook-turn gets a soft swish, each chat bubble lands a quiet pop on the beat, the differentiators tick lightly, and a soft chime rings on the outro wordmark as the music fades to silence.
