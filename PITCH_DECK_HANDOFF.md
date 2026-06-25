# Baltic Sentinel — Pitch Deck Handoff (for Claude Design)

> **Who this is for:** a design-focused Claude session whose only job is to build the **slide deck** for this hackathon. You are not writing code or touching the product. This document is self-contained — everything you need (story, facts, design system, slide-by-slide spec) is here. Read it top to bottom before designing.
>
> **The product already exists.** Its visual language is locked (it's a dark naval command console, see §4). **Your #1 constraint: the deck must look like it came from the same studio as the product.** A deck that doesn't match the console will read as bolted-on. Match it exactly — same palette, same fonts, same restraint.

---

## 1. What we're pitching (the 30-second version)

**Baltic Sentinel** is an **open, explainable early-warning system that protects the Baltic's undersea power and data cables** by fusing live ship-tracking with the GPS-jamming picture. A lightweight tripwire flags vessels behaving suspiciously over a cable corridor; a **swarm of Claude agents** investigates the vessel across open data (flag, sanctions/shadow-fleet, behavior, GPS-trust); the system produces a **plain-language threat dossier with a transparent reasoning trail, a recommended action, and a spoken watch-officer briefing.**

Built entirely on **free/open data**. Runs on **Aiven** (Kafka + Postgres), **Claude** (the agents), **ElevenLabs** (the voice). The incumbent (Windward) is closed, satellite-based, government-priced, and a black box. We are open, agentic, explainable, and democratized for the people priced out — the island councils and small coast guards who actually depend on these cables.

---

## 2. The two-audience problem (read this — it shapes the whole deck)

We are judged in **two different rooms** with **opposite priorities**. The deck must serve both, and you should design it so the *same slides* can be re-ordered/emphasized per room:

| Room | Who | What wins | Lead with |
|---|---|---|---|
| **Challenge judging** (Aiven, Anthropic, ElevenLabs reps — their *engineers*) | Technical | **Depth** — MCP integration, agent autonomy, voice-as-control-loop | Architecture, the live system, the rubric-specific slides (§6) |
| **Finalist / VC pitch** | Investors, general | **Story & impact** — the Baltic resilience + democratization narrative | The human stakes, Eagle S, "seeing it is a public good" |

**Design implication:** build a **modular deck** — a strong narrative spine that plays in the VC room, plus **3 sponsor-specific "depth" slides** (one each for Aiven / Anthropic / ElevenLabs) that we swap to the front when we're in front of that sponsor's engineers. Mark these clearly so they're easy to pull forward. Don't bury the technical depth — but don't let it drown the story either.

**Priority order across challenges (from strategy):** Aiven is the **primary** target (biggest prize, most natural fit). Anthropic is the **strong secondary** (nearly free — we use Claude anyway). ElevenLabs is **conditional/third** (one-way voice briefing does *not* meet their bar; treat as a demo flourish unless we commit to a voice-control console). So: **Aiven depth slide is the most polished; Anthropic close behind; ElevenLabs lighter.**

---

## 3. ⚠️ Naming — resolve before designing the title slide

**"Baltic Sentinel" collides** with NATO's operation **"Baltic Sentry"** *and* a real security publication **balticsentinel.eu**. **Do not finalize the title slide on "Baltic Sentinel."** Surface this to the team and pick from: **Anchor Watch**, **OpenWatch**, **Lighthouse**, **Tripwire**, **Seabed Watch**. Design the title slide so the name is a single swappable text element. (If forced to ship before a decision, use a working title and flag it.)

---

## 4. Design system — LOCKED (extracted from the live product)

Pull these directly from [frontend/prototype.html](frontend/prototype.html) and [frontend/variants/recon.html](frontend/variants/recon.html). **Do not invent a new palette.** This is a dark, restrained, naval/command-console aesthetic — think situation room, not SaaS landing page.

### Palette
| Token | Hex | Use in deck |
|---|---|---|
| `--bg` | `#070C16` | Slide background (near-black navy). Everything is dark. |
| `--surface` | `#0A1120` | Cards, panels |
| `--surface2` | `#0E1626` | Nested panels, code blocks |
| `--line` | `#1B2740` | Hairline dividers, borders |
| `--line2` | `#283651` | Stronger borders |
| `--text` | `#CDD8EA` | Body text (soft blue-white — never pure #fff except emphasis) |
| `--muted` | `#7E8DA9` | Secondary text, labels |
| `--faint` | `#566480` | Tertiary / captions |
| `--cyan` | `#4CC9E6` | **Primary accent** — system/UI, links, active state, data highlights |
| `--safe` | `#3FB68B` | Green — normal/safe status |
| `--watch` | `#F2B441` | Amber — caution, "recommended action" labels |
| `--threat` | `#F4543D` | **Red — threat, the Eagle S, the alert moment.** Use sparingly for maximum punch. |
| `--jam` | `#6B7FD7` | Indigo — the GPS-jamming layer |

### Typography
- **Geist** — headings + body (sans, system-ui fallback). Section headers are **UPPERCASE, letter-spaced ~0.15–0.18em**, in `--muted` (this is the console's signature — use it for slide kickers/eyebrows).
- **Geist Mono** — all data, telemetry, coordinates, IMO numbers, metrics, labels. Anything that reads as "machine output" is mono.
- **Instrument Serif** *(italic)* — the **human narrative voice.** In the product this renders the watch-officer's plain-language "story" verdict. In the deck, use italic Instrument Serif for the **emotional/narrative lines** (the kill-line, the "public good" line, pull-quotes). This serif-against-mono contrast IS the brand: machine precision + human judgment.

### Motifs to carry into the deck
- **Map as hero:** the Gulf of Finland on a dark-matter basemap, globe projection. Screenshot the real console (§7) — don't redraw it.
- **Sonar sweep / pulse** on the threat vessel (red dot, rotating cyan sweep) — from recon.html. Great for the "detection" slide.
- **Monospace telemetry overlays:** `GULF OF FINLAND · 140 contacts · 1 active threat`.
- **The dossier panel:** dark glass card, IMO/flag/speed in mono, a `THREAT · 90/100 · conf 0.86` pill in red, then the italic-serif story line. This card is the product's money shot — recreate or screenshot it.
- **Restraint:** lots of negative space, thin hairlines, one accent at a time. No gradients-for-decoration, no drop shadows except the subtle card glow, no stock photos, no emoji (except flag glyphs like 🇨🇰 which the product uses).

### Anti-patterns (AI-slop to avoid)
No purple-blue SaaS gradients, no rounded-everything, no three-column "feature card" grids with icons, no generic "AI brain" imagery, no clip-art ships. If it looks like a Lovable landing page, it's wrong. It should look like something a navy would actually stare at.

---

## 5. The facts (use these EXACT framings — they're fact-checked)

The Eagle S is our centerpiece. **Do not overclaim** — these wordings are vetted (HANDOFF §8):

- **Date:** "Christmas Day 2024" (25 Dec 2024). ✅
- **Damage:** Eagle S **knocked Estlink 2 offline for ~7 months** and **severed four telecom cables.** Say exactly this — "severed Estlink 2" is an overclaim (it was a fault, repaired Aug 2025).
- **Vessel:** Cook Islands flag (genuine flag of convenience), Russian shadow fleet, IMO **9329760**, owner Caravella LLC-FZ (UAE).
- **Sanctions angle (this is the strong one):** it was **NOT sanctioned at the time** — added to EU/UK/Swiss lists mid-2025. Frame as strength: *"it wasn't even on a list yet — we flag behavior, not paperwork."*
- **Mechanism:** anchor-drag is **alleged / "accused of"** (Finnish criminal case dismissed Oct 2025 on jurisdiction). Don't state it as fact.
- **GPS jamming:** do **not** claim jamming caused this incident. DO say: *"the Gulf of Finland is a documented, persistent GPS-jamming zone — so AIS here can't be trusted, which is exactly when you escalate to an independent sensor."*

**The kill-line (the deck's emotional peak — set it in italic Instrument Serif):**
> *"This is the Eagle S. On Christmas Day 2024 it dragged its anchor ~90 km across the Gulf of Finland, knocked Estlink 2 offline for seven months, and severed four telecom cables — and it wasn't even on a sanctions list yet. Our system would have flagged it on behavior before the cut."*

**The democratization line (the VC-room peak):**
> *"Today this kind of watch is sold to navies for the price of a warship's radar. The island council with one power line, the 60,000 on Gotland, the 90-person Åland municipality, three small states sharing a few patrol boats — they can't afford to see what's coming. We make seeing it a public good."*

**Beneficiaries (concrete, Baltic-specific):** Bornholm (~40k, single power cable, failed 2004/2010/2013/2026); Gotland (~60k, cables to Latvia & Lithuania both cut 2024–25); Åland (~30k, tiny municipalities); small-state coast guards (Estonia/Latvia/Lithuania, thin budgets); non-giant cable operators (e.g. Cinia/C-Lion1 — repairs need a ship from France, up to 2 weeks, so early warning is the *whole* value); marine insurers; journalists/OSINT.

---

## 6. Slide-by-slide spec

A ~10–12 slide spine. Sponsor-depth slides (★) are swap-to-front modules for challenge rooms. Times assume a ~3–4 min pitch.

| # | Slide | Content | Visual | Design notes |
|---|---|---|---|---|
| 1 | **Title** | Name (⚠️ see §3) + one-line: *"An open early-warning system for the Baltic's undersea lifelines."* | Dark map of Gulf of Finland, faint cable lines, single red threat dot. | Mono eyebrow `SUNSTEAD HACKATHON 2026`. Name in Geist. Restraint. |
| 2 | **The stakes** | Undersea cables carry the Baltic's power & data. They're cut, repeatedly. Repairs take weeks. | A real incident map / cable-cut timeline (2024–25). | Let one stat breathe per slide. Mono for numbers. |
| 3 | **The Eagle S** *(emotional hook)* | The kill-line (§5), in italic serif. | Console screenshot: Eagle S dossier, red sweep over Estlink 2. | This is the money slide. Serif quote + the real dossier card. |
| 4 | **Why nobody sees it coming** | AIS is noisy & spoofable; the GoF is a GPS-jamming zone; humans can't watch everything; incumbent tools are closed & priced for navies. | Split: noisy AIS vs the jamming layer (indigo hexes). | Sets up our differentiators. |
| 5 | **What we built** | The loop: tripwire → Claude agent swarm → explainable dossier → voice briefing → human decides. | The architecture diagram (clean, in palette). | Animate the flow if the tool supports it. Cyan = data flow. |
| 6 | **Live demo / how it works** | Operator launches investigation → agents light up → verdict + recommended action + voice. | Console screenshots or embedded recording; agent cards animating. | Mirror the real UI exactly. Show the reasoning trail (explainability = the pitch). |
| 7 ★ | **Aiven depth** *(primary)* | Kafka = the agent nervous system (topics); Postgres = agent memory; **provisioned & queried via the Aiven MCP — no backend boilerplate.** | The data-plane diagram from DEPLOYMENT_PLAN §2. | Most polished sponsor slide. Show topic names in mono. |
| 8 ★ | **Anthropic depth** *(secondary)* | A 24/7 autonomous monitor: scheduled, stateful, multi-step tool-using, human-in-the-loop escalation. "Not a prompt in a wrapper." | Agent loop: investigate → findings → synthesis → recommend → human. | Emphasize autonomy + HITL + "works live." |
| 9 ★ | **ElevenLabs depth** *(conditional/light)* | Voice is the watch officer — keeps the human oriented while the system acts. | Waveform + the spoken verdict text. | Keep light unless we commit to voice-control (see §2). |
| 10 | **Who it's for / impact** | The democratization line (§5) + the priced-out beneficiaries. | Map of the small communities (Bornholm/Gotland/Åland). | VC-room peak. Italic serif for the line. |
| 11 | **Why us / differentiator** | Open vs closed (Windward), agentic & explainable, GPS-fusion, democratized. We are NOT a satellite company — the open intelligence layer on open data. | 2-col compare: Windward (black box) vs us (open/explainable). | Honest framing. No overclaiming. |
| 12 | **Close** | Recommendation, not enforcement. "Seeing it is a public good." Team + ask + data attributions. | Logo/name, calm. | Attribution footer (see §8). |

**Re-order rules:** In the **Aiven room**, move 7 to slide 3-ish. **Anthropic room**, move 8 up. **VC room**, keep narrative order (1→6→10→11→12), demote sponsor slides to appendix.

---

## 7. Available assets

- **The live console** — best source of authentic visuals. Screenshot:
  - [frontend/prototype.html](frontend/prototype.html) — the full watch console (map + alerts rail + dossier panel + agent cards + voice player). This is the hero UI.
  - [frontend/variants/recon.html](frontend/variants/recon.html) — the cinematic "recon" view: globe, sonar sweep on the Eagle S, italic-serif story line. **Best single screenshot for slide 3.**
  - `gotham.html` / `civic.html` — alternative skins (same data, different mood) if you want range.
  - To capture: open the HTML in a browser (they load MapLibre + the data bundle `prototype_data.js`). Use the **browse** skill / a screenshot tool for clean captures at slide resolution.
- **Sample dossier data:** [demo_assets/sample_assessment.json](demo_assets/sample_assessment.json) — real verdict/finding shapes for accurate mockups.
- **Architecture diagrams:** ASCII versions in [DEPLOYMENT_PLAN.md](DEPLOYMENT_PLAN.md) §1–2 and [HANDOFF.md](HANDOFF.md) §4 — redraw these in-palette.
- **Fonts:** Geist, Geist Mono, Instrument Serif — all on Google Fonts (already linked in the HTML; embed/inline for the deck).

---

## 8. Required attribution footer (closing slide)

Non-commercial hackathon prototype. Credit on the close slide:
> Digitraffic / Fintraffic (CC BY 4.0) · GPSJam.org (John Wiseman) / ADS-B Exchange (CC-BY) · TeleGeography Submarine Cable Map (CC-BY-NC-SA) · OpenSanctions (CC-BY-NC). Built on Aiven, Claude, ElevenLabs.

---

## 9. Format & deliverable

- **Recommended format:** a self-contained **HTML deck** (one file, inline CSS, dark theme) — it'll match the product's exact CSS tokens natively and renders anywhere. Render it via the **Artifact** tool so the team can review/share. (Load the `artifact-design` skill first.) Reveal.js-style sections or simple full-screen `<section>`s both work.
- **Alternative:** if the team prefers Google Slides / PowerPoint / Gamma, deliver the same content + the exact palette/font spec so it stays on-brand.
- **Aspect ratio:** 16:9.
- **Tone of copy:** terse, confident, honest. No marketing fluff. Every claim defensible (§5). Let the map and the dossier do the talking.

**Before you start:** confirm with the team (a) the final name (§3), (b) HTML-deck vs Slides, and (c) whether ElevenLabs gets a full depth slide or stays a flourish. Then build the spine first (slides 1–6, 10–12), sponsor-depth slides second.
