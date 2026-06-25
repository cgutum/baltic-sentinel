# Baltic Sentinel — Build Handoff & Roadmap (v2, validated)

> **What this is:** the build plan for our 24h hackathon prototype, **after pressure-testing every external dependency by actually connecting to it** (2026-06-24). Everything in §1 was tested live, not assumed. Hand sections to Claude Code one milestone at a time. Build *toward the 90-second demo*, not toward completeness.

---

## 0. TL;DR for my buddy

- **The idea works and the data is real.** I connected to every external service. AIS, GPS-jamming, sanctions, and cable data are all live and accessible today.
- **Two big changes from the original plan:**
  1. **Digitraffic (Finnish open AIS) is our primary map feed**, not AISStream — no API key, covers the whole Baltic, and the browser can call it directly (which makes the Vercel + refresh-button plan trivial). AISStream still works (tested with our key) and becomes our Kafka ingest source.
  2. **The GPS-jamming "fusion" is reframed**: jamming is a *regional* "this corridor is untrustworthy" condition, not a per-vessel smoking gun. This is honest and still compelling. (The data backs it — there IS real jamming in the eastern Gulf of Finland.)
- **The Eagle S replay is our centerpiece and our insurance policy** — it runs the same pipeline as live data, so even if every live service dies on stage, the demo still works.
- **One open decision:** where the always-on Python backend lives (see §5). Frontend → Vercel is settled.

---

## 1. What we validated (evidence, tested 2026-06-24)

| Dependency | Status | What we actually found |
|---|---|---|
| **AISStream.io** (with our key) | ✅ **Works** | Pulled 22 live AIS messages in 25s for the Gulf of Finland box — real ships (GABRIELLA, FLEVOBORG) with valid lat/lon. ~1 msg/s for our region (totally manageable). **No CORS** → must be consumed by our backend, not the browser. Beta, no SLA → don't make it the *only* feed. |
| **Digitraffic Marine AIS** | ✅ **Works, better fit** | 18,573 vessels across the whole Baltic; **140 live vessels in the Gulf of Finland** after filtering. Covers Estonian side, Estlink corridor, Ust-Luga, St. Petersburg, Gulf of Riga. **No API key. CORS open → browser can call it directly.** REST with 60s cache = perfect for a refresh button. |
| **GPSJam** (GPS interference) | ✅ **Works** | Downloaded `2026-06-23-h3_4.csv` (46,605 H3 hexes). Decoded them: **21 hexes in the Gulf of Finland show ≥10% GPS degradation**, concentrated in the **eastern Gulf near the Russian border** (Kotka/Vyborg/Ust-Luga) — exactly where our story needs it. |
| **OpenSanctions maritime** | ✅ **Works, tiny file** | Found the dedicated **`maritime.csv` (~3.7 MB)** — not the 488 MB dump. No auth, CC-BY-NC. Columns: `imo, flag, mmsi, risk, countries, name, aliases`. The `risk` column even has **`mare.detained`** tags = a free port-state-control detention signal. |
| **TeleGeography cables** | ✅ **Works (telecom only)** | GeoJSON endpoints return live data. **Power cables (Estlink) are NOT in it** — hardcode those from landing points. CC-BY-NC. |
| **Aiven MCP** | ⏳ Access coming | Confirmed real: `mcp.aiven.live/mcp` provisions Kafka+Postgres, creates topics, runs SQL. **Use the bare URL (no `?read_only=true`)** or writes silently no-op. Free tier now includes Kafka. ⚠️ Free Kafka **auto-powers-off when idle** — keep traffic flowing during judging. |
| **Vercel** | ✅ Settled (frontend) | Hosts the MapLibre frontend. Cannot host always-on Python (no WebSockets, no background workers) — see §5. |

**Bottom line: green light.** No dependency is a blocker.

---

## 2. North-star demo (build for THIS — 90 seconds)

1. Live map of the Gulf of Finland with **real ships** moving (Digitraffic).
2. Real undersea cables + a faint **GPS-jamming layer** (GPSJam hexes).
3. The scripted **"Eagle S" replay** drifts slowly over the **Estlink 2** corridor, inside a jammed zone, and its AIS goes quiet.
4. A **tripwire fires** → the **agent swarm lights up** (agent cards animate as Kafka `agent.findings` arrive).
5. ~10s later: **red alert** + **dossier panel** (flag, sanctions/detention hit, behavior, GPS-context finding, reasoning trail, recommended action) + an **ElevenLabs voice briefing**.
6. **Kill line (fact-checked, see §8):** *"This is the Eagle S. On Christmas Day 2024 it dragged its anchor ~90 km across the Gulf of Finland, knocked Estlink 2 offline for seven months, and severed four telecom cables — and it wasn't even on a sanctions list yet. Our system would have flagged it on behavior before the cut."*

**If a piece isn't on screen in those 90 seconds, it's out of scope.**

---

## 3. Scope

**In (MVP):**
- One region: **Gulf of Finland** (Estlink 1/2, C-Lion1, Balticconnector).
- Live AIS on the map (Digitraffic, browser-direct).
- AISStream → Kafka `ais.raw` ingest (the Aiven "bridge").
- ~10–15 hardcoded cables with buffered corridors.
- GPS-jamming layer (daily GPSJam data).
- Tripwire detection (R1 + R3, R2 if easy).
- **4 specialist agents + 1 synthesis agent + voice.**
- Dossier panel + map alerts.
- Eagle S replay mode.

**Out (do not build):**
- Satellite SAR/EO/RF (that's Windward's moat — we don't claim it).
- Real historical AIS archives / model training.
- Auth, multi-user, accounts, deployment hardening.
- PNT "fallback navigation."
- Anything kinetic — we *recommend* human action, never automate response.

---

## 4. Architecture (revised)

```
        ┌─────────────────────────────────────────────┐
        │              AIVEN (the "bridge")            │
        │   Kafka topics  +  PostgreSQL (state/log)    │
        └─────────────────────────────────────────────┘
              ▲              ▲                ▲
 AISStream ─ws─►[ingest]──►ais.raw           │
 (our key)        │                          │
                  ▼                          │
            [tripwire]──►vessel.suspicion    │
                  │                          │
                  ▼                          │
           [orchestrator]──fan-out──►(4 agents ∥)──►agent.findings
                  │                          │
                  ▼                          │
           [synthesis]──►threat.assessment   │
                  │                          │
                  ▼                          │
           [ElevenLabs TTS]──►audio          │
                                             │
 ───────── always-on Python backend ─────────┘
        │  also serves REST: GET /vessels, GET /alerts,
        │  POST /investigate, GET /assessment/:id, /findings (SSE)
        ▼
 Vercel frontend (MapLibre)
   • polls backend GET /vessels every ~5–10s (refresh button + auto)
   • polls Digitraffic DIRECTLY as the map's primary/fallback feed (CORS open)
   • on alert: dossier panel, swarm animation, plays audio
```

**Why two AIS sources:** Digitraffic feeds the **map** reliably (browser-direct, no key, no backend dependency). AISStream feeds the **Kafka pipeline** (the Aiven challenge needs data flowing through Kafka, and AISStream's WebSocket push is the natural producer). If one dies, the demo degrades gracefully instead of breaking.

**Kafka topics:**
- `ais.raw` — normalized AIS positions + static data (from AISStream ingest)
- `vessel.suspicion` — tripwire hits (rule + cable)
- `agent.findings` — one message per agent finding (tagged with agent name → drives the swarm animation)
- `threat.assessment` — synthesized verdict + recommended action

> Use the **Aiven MCP** to create the Kafka service, topics, and Postgres tables in-loop — that's literally the challenge ("Aiven MCP is the bridge").

---

## 5. Hosting — the one open decision

Vercel hosts the **frontend** (settled). The always-on Python (AISStream ingest + Kafka consumers + agents) **cannot** run on Vercel (no WebSockets, no background workers, 300s function cap). Three options for the backend, in order of recommendation for a hackathon:

| Option | What | Pro | Con |
|---|---|---|---|
| **A — Laptop + tunnel (recommended for demo day)** | Run the Python backend on a laptop; expose it with `cloudflared`/`ngrok`; Vercel frontend points at the tunnel URL. | Zero deploy friction, full control, fastest to iterate, easiest to debug live. | Tied to the laptop/wifi (mitigated by the recorded backup). |
| **B — Render / Railway free tier** | Deploy the Python backend as one always-on service. | Public URL, survives laptop sleep. | ~15 min of deploy setup; free tiers can cold-start/sleep. |
| **C — Pure Vercel serverless** | Agents as a streaming serverless function; map polls Digitraffic direct; Kafka produced one-shot per investigate. | No second host. | Kafka-from-serverless connection churn + cold start = the riskiest path; no always-on AIS→Kafka ingest. |

**Recommendation: build for A, keep B as the deployed backup.** Decide at M0 and don't revisit. Either way the frontend is Vercel and the map can always fall back to polling Digitraffic directly.

---

## 6. Tech stack (pick the boring option)

- **Language:** Python backend, JS/HTML frontend.
- **AIS ingest:** Python `websockets` → AISStream (key in `.env`). **Confirmed working.**
- **AIS map feed:** browser `fetch` → Digitraffic REST (no key). **Confirmed working.**
- **Kafka:** `confluent-kafka` (Aiven = SSL; use dotted config keys `ssl.ca.location` / `ssl.certificate.location` / `ssl.key.location` — NOT kafka-python's underscore keys).
- **Geo:** `shapely` for corridor buffers + point-in-polygon; `h3` to convert GPSJam hexes to polygons.
- **Agents:** `anthropic` SDK. `claude-sonnet-4-6` for the 4 specialists (fast/cheap), `claude-opus-4-8` for synthesis. Run specialists in parallel with `asyncio.gather`.
- **Backend API:** FastAPI (REST + SSE for the swarm animation).
- **Frontend:** MapLibre GL JS + free Carto/MapLibre demo basemap. Plain HTML/JS or tiny Vite app. Ships = GeoJSON symbol layer; cables = line layers; jamming = fill layer; dossier = side panel.
- **Voice:** ElevenLabs TTS REST.

---

## 7. Data sources — exact, validated endpoints

### 7.1 Digitraffic Marine AIS (PRIMARY map feed — no key)
- Live positions (GeoJSON): `GET https://meri.digitraffic.fi/api/ais/v1/locations`
- Static/voyage metadata: `GET https://meri.digitraffic.fi/api/ais/v1/vessels`
- **Required header:** `Accept-Encoding: gzip` (else HTTP 406). Send a `Digitraffic-User: baltic-sentinel-hackathon` header (courtesy, raises rate limit). CORS open → callable from the browser.
- Join `/locations` (dynamic: `mmsi, sog, cog, heading, navStat, timestampExternal`) with `/vessels` (static: `name, imo, shipType, destination, draught, referencePointA/B/C/D` for dimensions) on `mmsi`.
- ⚠️ **Filter stale ghosts:** keep only vessels with `timestampExternal` within ~10–15 min, or you'll plot positions from 2018.
- Poll once/minute (data is 60s-cached); use the refresh button + a quiet auto-interval.

### 7.2 AISStream.io (Kafka ingest source — needs our key, backend-only)
- URL: `wss://stream.aisstream.io/v0/stream`
- **Send subscription within 3s of connecting** or it closes. Subscription (note triple `[[[`, order is `[lat, lon]`):
  ```json
  {
    "APIKey": "<AISSTREAM_API_KEY>",
    "BoundingBoxes": [[[59.0, 22.0], [60.7, 30.0]]],
    "FilterMessageTypes": ["PositionReport", "ShipStaticData"]
  }
  ```
- Parse via `msg["Message"][msg["MessageType"]]`. Gotchas: in the body MMSI is `UserID`, lat/lon are `Latitude`/`Longitude` (capitalized); in `MetaData` they're lowercase + `MMSI` + `ShipName`. Static data: `ImoNumber`, `Name`, `Type`, `Dimension{A,B,C,D}` (length=A+B, beam=C+D).
- Invalid key returns `{"error": "Api Key Is Not Valid"}`; any close (incl. 1006) → reconnect with backoff. The official client does NOT auto-reconnect — wrap it yourself.

### 7.3 GPSJam (GPS interference — daily, no key)
- `GET https://gpsjam.org/data/YYYY-MM-DD-h3_4.csv` (yesterday's date; today's not published until the day completes).
- Columns: `hex, count_good_aircraft, count_bad_aircraft`. Compute `pct = bad/(good+bad)`. Keep hexes with `pct ≥ 0.10` AND `(good+bad) ≥ 3` (drop tiny samples).
- Use `h3.cell_to_latlng(hex)` / `h3.cell_to_boundary(hex)` to render and to test vessel-in-hex.
- ⚠️ Res-4 hexes are large (~15–30 km) and the data is sparse over water → treat jamming as a **regional condition**, not a precise per-vessel signal. Cache the day's file locally at startup.

### 7.4 OpenSanctions maritime (sanctions + detentions — no key)
- Resolve current build: `GET https://data.opensanctions.org/datasets/latest/maritime/index.json` → take the `maritime.csv` artifact URL (~3.7 MB).
- Columns: `type, caption(name), imo, risk, countries, flag, mmsi, id, datasets, aliases`. Match by IMO or normalized name. `risk` tags include `mare.detained` (PSC detention) and `reg.warn`. CC-BY-NC.
- Download once at startup; match locally (no live calls at demo time).

### 7.5 TeleGeography cables (telecom routes — no key)
- `https://www.submarinecablemap.com/api/v3/cable/cable-geo.json` (MultiLineString routes), `.../landing-point/landing-point-geo.json`.
- **Telecom only — Estlink/power cables absent.** Hardcode power-cable corridors between known landing points. Routes are stylized/approximate → always buffer into **corridors** (~2–5 km), never use exact lines. (This is also a pitch point: "exact routes are classified — that's the vulnerability.")

---

## 8. Pitch facts — corrected & fact-checked (use these exact framings)

- **Date:** "Christmas Day 2024" ✅ (25 Dec 2024).
- **Damage:** Eagle S **knocked Estlink 2 offline for ~7 months** (NOT cleanly "severed" — it was a fault, repaired Aug 2025) and **severed four telecom cables** ✅. Use this wording; "severed Estlink 2" is an overclaim.
- **Vessel:** Cook Islands flag (genuine flag of convenience) ✅, Russian shadow fleet ✅, owner Caravella LLC-FZ (UAE), IMO 9329760.
- **Sanctions — use this angle:** it was **NOT sanctioned at the time of the incident** (added to EU/UK/Swiss lists mid-2025). Frame as a strength: *"it wasn't even on a list yet — we flag behavior, not paperwork."* Today our sanctions agent gets a real hit, so the live demo works — just say "current lists."
- **Mechanism:** anchor-drag is **alleged** (Finnish criminal case dismissed Oct 2025 on jurisdiction) — say "accused of."
- **GPS jamming:** Do NOT claim jamming caused this specific incident — unsupported. DO say: *"the Gulf of Finland is a documented, persistent GPS-jamming zone, and Finnish authorities suspect shadow-fleet tankers themselves as the jammers — so AIS here can't be trusted, which is exactly when you escalate to an independent sensor."* (This is the honest, defensible version of our differentiator.)

---

## 9. Tripwire rules

Run on the `ais.raw` stream; emit to `vessel.suspicion`. Tune so the Eagle S replay reliably fires **R1 + R3**.

- **R1 — Loiter over cable:** speed `< 3 kn` AND inside a cable corridor for `> 10 min` (shorten to ~60–90s for the live demo).
- **R2 — Going dark near cable:** vessel last seen within ~5 km of a corridor stops transmitting for `> N` min (AIS gap).
- **R3 — Untrustworthy-AIS zone (the fusion):** vessel position inside a "bad" GPSJam hex AND within a corridor buffer → flag because AIS evidence here is unreliable.
- **R4 (bonus) — Anchor-drag signature:** slow + erratic heading changes over a corridor.

---

## 10. The agents

Orchestrator consumes `vessel.suspicion`, pulls the vessel's recent track + static data from Postgres, fires the 4 specialists **in parallel**, each publishing to `agent.findings` (tagged with its name → UI animates the swarm). Then synthesis → `threat.assessment` → ElevenLabs narration. Keep outputs short + structured JSON: `{finding, severity_contribution, evidence}`.

| Agent | Input | Source | Output |
|---|---|---|---|
| **Flag & Identity** | MMSI, IMO, name | MMSI→flag (MID table); flag-of-convenience list | flag risk, identity inconsistencies |
| **Sanctions & Record** | IMO, name | local `maritime.csv` | sanctioned? shadow-fleet? `mare.detained`? |
| **Behavior** | recent track | pure reasoning over track | loiter / anchor-drag / dark-gap vs claimed nav status |
| **EM-environment** *(differentiator)* | position | GPSJam hexes | in a jammed zone? is AIS here trustworthy? |
| **Synthesis / Watch-Officer** | all findings | — | LOW/MED/HIGH + confidence + plain-language summary + reasoning trail + recommended action |
| **Briefing** | the assessment | ElevenLabs | spoken briefing |

**Recommended actions (awareness-side only):** escalate dossier to coast guard; alert cable operator to pre-position a repair vessel; **task an independent sensor (patrol/MPA/drone) because AIS can't be trusted here**; or continue monitoring at raised alert. Never kinetic.

---

## 11. Milestones (each independently demoable — stop anywhere, still have a story)

- **M0 — Setup (~1h).** Repo scaffold (`https://github.com/cgutum/baltic-sentinel.git`). Aiven MCP → create Kafka service + topics (§4) + Postgres tables (§12). Keys in `.env`. **Decide hosting (§5) now.** Pre-download GPSJam + `maritime.csv` + cable GeoJSON.
  - *Done when:* produce/consume a test message on `ais.raw`; connect to Postgres.

- **M1 — Live ships on a map (~2–3h). ← already a demo.** MapLibre frontend on Vercel polls **Digitraffic** directly; ships colored by type, details on click. *(No backend needed for this milestone — browser-direct.)*
  - *Done when:* real ships move on screen.

- **M2 — Cables + tripwire (~3h).** Draw hardcoded cable corridors + GPSJam layer. Stand up the backend: AISStream → `ais.raw` → Postgres. Implement R1 + R3, emit `vessel.suspicion`, flash the offending vessel red.
  - *Done when:* a slow vessel over a corridor lights up suspicious.

- **M3 — First agent → dossier (~2h).** Orchestrator consumes `vessel.suspicion`; run the **Sanctions** agent (local CSV); show a basic dossier panel.
  - *Done when:* a suspicious vessel produces a real sanctions/detention finding on screen.

- **M4 — Full swarm + synthesis (~3h).** Add Flag, Behavior, EM-environment in parallel → `agent.findings`; add Synthesis → `threat.assessment`. Animate agent cards as findings arrive (SSE). Fill the dossier with reasoning trail + recommended action.
  - *Done when:* one tripwire produces a complete, multi-agent, explainable verdict. **← this is already a winning demo.**

- **M5 — Voice (~1h).** Pipe the assessment through ElevenLabs; play on alert.
  - *Done when:* the verdict is spoken aloud.

- **M6 — Eagle S replay + polish (~2h).** Add the scripted replay (§13). Tune thresholds so it reliably fires. Polish the alert moment, dossier, kill-line overlay.
  - *Done when:* the full §2 demo runs start-to-finish on command.

**Priority if time runs short:** M0→M4 is the win. M5/M6 are prize-stacking + polish. Don't over-build Kafka plumbing at the expense of M4.

---

## 12. Data model (Postgres — minimal)

```sql
vessels(mmsi PK, imo, name, type, flag, last_lat, last_lon, last_speed,
        last_course, nav_status, last_seen)
tracks(id PK, mmsi, lat, lon, speed, course, ts)          -- rolling window
suspicion_events(id PK, mmsi, rule, cable_id, ts, details_json)
assessments(id PK, mmsi, suspicion_id, level, confidence,
            summary, reasoning_json, recommended_action, ts)
cables(id PK, name, type, corridor_geojson)               -- or load from file
```

---

## 13. The Eagle S replay (centerpiece + insurance)

- **Replay mode:** a script injects a synthetic vessel's track into `ais.raw` exactly like a real ship, so it flows through the *same* tripwire → agents → dossier path (no special-casing).
- Reconstruct a slow drift across the **Estlink 2** corridor, inside a jammed GPSJam hex, with an AIS gap.
- Give it realistic static data: Cook Islands flag, name/IMO (9329760) that matches a real entry in `maritime.csv` so the sanctions agent gets a true hit, and a `mare.detained` tag so the record agent has something real.
- **Be transparent in the pitch that it's a reconstruction.** Run it alongside the live map so judges see both real traffic and the staged incident.
- Because it runs the full pipeline offline, **the demo works even if every live API is down.**

---

## 14. Code starters (validated against real responses)

**Digitraffic poll (browser-direct, primary map feed):**
```js
// runs in the frontend; refresh button + setInterval(…, 60000)
async function loadShips() {
  const res = await fetch("https://meri.digitraffic.fi/api/ais/v1/locations", {
    headers: { "Digitraffic-User": "baltic-sentinel-hackathon" }, // gzip auto in browser
  });
  const geo = await res.json();
  const cutoff = Date.now() - 15 * 60 * 1000;
  geo.features = geo.features.filter(f => f.properties.timestampExternal >= cutoff); // drop ghosts
  map.getSource("ships").setData(geo);
}
```

**AISStream → Kafka (backend ingest, confirmed working):**
```python
import asyncio, json, websockets
# from confluent_kafka import Producer  # SSL config with Aiven dotted keys

async def run():
    sub = {"APIKey": AISSTREAM_API_KEY,
           "BoundingBoxes": [[[59.0, 22.0], [60.7, 30.0]]],
           "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}
    async for ws in websockets.connect("wss://stream.aisstream.io/v0/stream"):  # auto-reconnect
        try:
            await ws.send(json.dumps(sub))  # must be within 3s
            async for raw in ws:
                m = json.loads(raw)
                if "error" in m: raise RuntimeError(m["error"])
                body = m["Message"][m["MessageType"]]
                # normalize (MMSI = body["UserID"]) -> produce to "ais.raw"
        except websockets.ConnectionClosed:
            continue  # reconnect
```

**GPSJam decode (validated):**
```python
import requests, h3
rows = requests.get("https://gpsjam.org/data/2026-06-23-h3_4.csv", timeout=30).text.splitlines()[1:]
bad_hexes = []
for ln in rows:
    hx, g, b = ln.split(","); g, b = int(g), int(b)
    if g + b >= 3 and b / (g + b) >= 0.10:
        bad_hexes.append(hx)
def in_jammed_zone(lat, lon):
    return h3.latlng_to_cell(lat, lon, 4) in set(bad_hexes)
```

**Corridor proximity (tripwire):**
```python
from shapely.geometry import Point
# corridor = cable_line.buffer(0.03)  # ~3 km in degrees (rough; fine for demo)
def over_cable(lat, lon, corridor):
    return corridor.contains(Point(lon, lat))   # note (x=lon, y=lat)
```

**Parallel agent swarm (orchestrator):**
```python
import asyncio
async def investigate(vessel):
    findings = await asyncio.gather(
        flag_agent(vessel), sanctions_agent(vessel),
        behavior_agent(vessel), em_agent(vessel))
    for f in findings:
        produce("agent.findings", f)          # drives the UI swarm animation
    assessment = await synthesis_agent(vessel, findings)
    produce("threat.assessment", assessment)
    return assessment
```

---

## 15. Env

```bash
# Aiven MCP (use the BARE url — no ?read_only=true)
claude mcp add --transport http aiven-mcp https://mcp.aiven.live/mcp

# .env
AISSTREAM_API_KEY=92e8984b...        # tested, working
ANTHROPIC_API_KEY=...
ELEVENLABS_API_KEY=...
KAFKA_BOOTSTRAP=...                   # from Aiven
KAFKA_SSL_CA=...                      # Aiven CA cert path
KAFKA_SSL_CERT=...                    # Aiven access cert path
KAFKA_SSL_KEY=...                     # Aiven access key path
POSTGRES_URI=...                      # from Aiven
# Digitraffic, GPSJam, OpenSanctions, TeleGeography = NO keys needed
```
> Keep the AISStream key out of git. `.env` in `.gitignore`.

---

## 16. Gotchas & decisions (validated)

- **Digitraffic = browser-direct** (CORS open). AISStream = **backend-only** (no CORS). Don't mix these up.
- **Filter Digitraffic by `timestampExternal`** or you plot ships from 2018.
- **Aiven free Kafka auto-powers-off when idle** — keep AIS flowing during judging; provision Kafka *first*, not at hour 20.
- **Aiven MCP: bare URL only**, or write operations silently no-op.
- **confluent-kafka uses dotted SSL keys** (`ssl.ca.location`), not kafka-python underscores.
- **GPSJam is a regional layer**, not a per-vessel signal — frame the differentiator as "AIS untrustworthy here."
- **Cables = corridors, never exact lines.** Estlink isn't in TeleGeography → hardcode it.
- **Local CSVs > live calls at demo time** for sanctions/cables/jamming — cache at startup.
- **Keep agent outputs short** — long responses make the swarm feel slow on stage.
- **Don't overclaim** — open/agentic/explainable layer on open data; we are NOT a satellite company. Awareness-side only, never kinetic.

---

## 17. Demo-day checklist

- [ ] Record a full screen-capture backup of the §2 demo.
- [ ] Pre-stage the Eagle S replay as a one-command trigger.
- [ ] Cache all third-party data locally before going on stage.
- [ ] Confirm Aiven Kafka isn't powered-off (send a heartbeat message).
- [ ] Kill-line overlay ready (§8 wording).
- [ ] Test ElevenLabs audio on the venue's sound output.
- [ ] Decide who drives (one on demo, one on mic).
- [ ] Tunnel/backend URL confirmed reachable from the Vercel frontend.

---

## 18. Attribution (UI footer)

Digitraffic / Fintraffic (CC BY 4.0) · AISStream.io · GPSJam.org (John Wiseman) / ADS-B Exchange (CC-BY) · TeleGeography Submarine Cable Map (CC-BY-NC-SA) · OpenSanctions (CC-BY-NC). Non-commercial hackathon prototype.

---

## 19. Stretch (only if ahead)

- OpenSky live ADS-B for near-real-time GPS integrity instead of daily GPSJam.
- An OSINT agent that web-searches recent reporting on the vessel.
- A second region (Gotland / central Baltic) to show it generalizes.
- ClickHouse for fast track replay/analytics.
```
