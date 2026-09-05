# Post-migration audit — 2 September 2026

## Executive result

The migration to the x86_64 server is operational. All 13 Compose services are
running and healthy with zero Docker restarts. Docker, containerd and libvirt
are active together, KVM bridges remain present, SQLite journals pass
`PRAGMA integrity_check`, and the host has approximately 77 GB free.

The collectors are not merely alive: they are producing fresh records. The
first official 1 September bars for both current daily forward candidates were
written successfully after migration.

The main issue is not collector reliability but product clarity. The web UI
mixes current operations, retired strategies, rejected research, raw audit
payloads and generic OctoBot real-trading controls. This makes the dashboard
large and difficult to interpret and creates several contradictions with the
actual runtime.

## Runtime inventory

| Service | Current evidence | Assessment |
| --- | --- | --- |
| `octobot-local` | Healthy; port 5001; simulator active; real trader disabled; buy/sell disabled in profile | Keep as UI and audit runtime |
| `market-observer` | Healthy; 19 symbols; fresh 15-minute bucket; about 98.2% coverage | Keep until Carry V1.1 readiness/evaluation completes |
| `cross-venue-observer` | Healthy; 18 symbols; fresh 15-minute compressed records | Technically sound, but no currently approved downstream strategy; optional |
| `scalping-observer` | Healthy and connected; more than 35 million book events | Keep while execution-shadow is collecting; reassess after 27 Sep |
| `execution-shadow` | Healthy; 964 decisions, 951 completed outcomes; 16.7% progress | Keep through frozen end at 27 Sep 09:30 UTC |
| `forward-carry-gatekeeper` | Healthy; waiting for readiness; no economic artifacts | Keep; earliest data readiness 21 Sep |
| `diversified-forward-observer` | Healthy; first official record written | Keep; current primary forward experiment |
| `diversified-forward-gatekeeper` | Healthy; waiting for 28 Feb 2027 cutoff | Keep |
| `breadth-forward-observer` | Healthy; first official record written; no network | Keep; current challenger forward experiment |
| `operations-reporter` | Healthy; hourly status and verified daily backups | Keep |
| `trend-shadow` | Healthy but historically marked retired | Stop after confirming no explicit need for legacy comparison |
| `v5-paper` | Healthy; retired model still evaluating every 15 minutes | Stop unless deliberate renewed paper evidence is wanted |
| `v5-broker` | Healthy; real trader false, simulated trader true | Stop together with V5 paper if V5 remains retired |

## Data and integrity

- `ai_decisions.sqlite`: integrity `ok`.
- `execution-shadow/journal.sqlite`: integrity `ok`.
- `v5-paper/binance/v5-paper.sqlite`: integrity `ok`.
- `v5-paper-bridge.sqlite`: integrity `ok`.
- Operations backups for the small journals are verified and content hashed.
- The Level-5 database is approximately 13 GB and intentionally checked only
  offline so that an integrity scan cannot block the latency-sensitive
  collector.
- Persistent storage is concentrated in `backtesting` (about 13 GB),
  `scalping` (about 13 GB) and `shadow` (about 3.2 GB).
- Docker has 18 anonymous volumes attached to current containers. They report
  zero material size, so there is no urgent disk cleanup; replacing unnecessary
  image-declared anonymous volumes with explicit empty read-only binds would
  improve clarity on the next Compose revision.

## Recovered anomalies

The following errors occurred after startup but recovered without container
restart:

1. execution-shadow attempted to open the Level-5 SQLite database three times
   before it was available;
2. scalping-observer detected two five-second stale-book intervals, failed
   closed and reconnected;
3. market-observer received one public HTTP 429 and recovered on a later cycle;
4. both OctoBot web runtimes log optional tentacle import errors and missing
   login information. The missing credentials are expected for public-data and
   paper-only operation; the unused optional tentacles should be excluded from
   the local profiles to eliminate noisy false alarms.

These are resilience events rather than ongoing failures. They should still be
counted explicitly in the operations summary instead of being visible only in
container logs.

## Configuration inconsistencies

### Retired services are running

The operations reporter declares `main_legacy`, `trend_shadow` and `v5`
retired. The dashboard therefore labels them archived. After the requested
full-stack migration startup, trend-shadow, V5 runner and V5 broker are all
healthy and active. V5 also declares `paper_orders_authorized=true`.

This is safe from real trading because its broker reports `real_trader=false`,
but it is conceptually inconsistent. Choose one source of truth:

- preferred: keep retired services stopped and expose their journals only;
- alternative: explicitly reclassify them as renewed paper/shadow experiments
  with a new forward protocol.

Simply running a retired model while the UI calls it archived should not remain
the steady state.

### Real-trading controls remain visible

Ports 5001 and 5002 bind to all IPv4 and IPv6 interfaces, while UFW is inactive.
The generic OctoBot layout still renders “Switch to real trading” controls even
though this installation is contractually paper-only. Host/network perimeter
rules may provide protection, but the application should also hide or disable
the real-trading switch for local paper-only profiles.

### Current breadth experiment is missing from Strategy Status

Breadth Forward V2 is active and has its first official record, but the current
`/strategy_status` controller and template do not show it. The page gives much
more space to rejected or retired experiments than to this current forward
candidate.

## Dashboard audit

### Current size

| Page | Rendered size | Main problem |
| --- | ---: | --- |
| `/` | 36 KB | Seven research overlays around one operational chart |
| `/strategy_status` | 275 KB | 817-line template, 277 card-class elements, archive mixed with live state |
| `/ai_decisions` | 1.72 MB | 250 decisions with full pretty-printed input/output JSON |

Local response time is currently fast, but payload size and visual density make
the information difficult to use. The issue is information architecture, not
server CPU.

### Recommended operational dashboard

The default landing page should answer only five questions:

1. Is the system healthy?
2. Are real orders impossible?
3. What paper position or pending order exists now?
4. Are active collectors fresh?
5. Which forward gates are progressing and when can they be evaluated?

Recommended top-level sections:

- **Safety:** real trader off, credentials absent, order authorization state.
- **Paper account:** equity, open position, pending order, last decision and
  cumulative closed-paper P&L.
- **Collectors:** one compact row per active collector with freshness, coverage,
  next gate and recovered-error count.
- **Forward research:** only Diversified 50/50, Breadth V2, Execution V2 and
  Carry V1.1.
- **Alerts:** stale data, integrity failure, restart, authorization mismatch or
  disk threshold.

### Content to remove from the default view

- V5 statistical and calibration cards when V5 remains retired.
- V3/V14 weights, candidates and income simulation from the live status page.
- Microstructure Regime V1/V2 rejected-result cards.
- H1, H2, Perfect Map, forecast V2, path V1 and causal-signal overlays as
  default chart toggles.
- The ETH chart that reuses an unvalidated BTC model.
- Full raw JSON for every decision.
- Duplicate explanations of “orders disabled” repeated inside every research
  card; show the invariant once in the Safety header.
- Generic “Switch to real trading” and real-account UI for paper-only profiles.

No research artifact needs deletion. Move these elements to a read-only
**Research Archive** page linked to `HISTORY.md`, grouped by family and final
verdict.

### AI Decisions page

Keep the aggregate counts and the paper outcome table, but:

- show 25 recent decisions by default rather than 250;
- use server-side pagination or a date/action filter;
- show action, approval, guard reason, confidence and timestamp in the table;
- load raw input/output JSON only on demand in a detail view;
- move the old backtest-capital card to the Research Archive because it is not
  live account equity;
- rename the page **Decision Audit** to clarify its purpose.

This should reduce the default response from roughly 1.72 MB to well below
200 KB without losing audit access.

### Strategy Status page

Replace the monolithic page with:

- an operational summary;
- a compact collector table;
- four active experiment cards;
- a link to archived strategies.

The current archived sections should be data-driven from the strategy ledger
rather than maintained as large custom template blocks. Breadth V2 must be
added before any retired detail is restored.

### Chart page

Default to price, actual paper orders/positions and at most the current live
decision marker. Put rejected/hindsight overlays behind a single off-by-default
“Research overlays” disclosure. Remove the invalid ETH/BTC-model comparison
from the operational landing page.

## Proposed cleanup sequence

1. Resolve whether V5 and trend-shadow are retired or intentionally resumed.
2. Hide real-trading controls and bind the web ports only to the intended
   management interface or localhost/reverse proxy.
3. Add Breadth V2 to the active status model.
4. Split Strategy Status into Operations and Research Archive.
5. Reduce AI Decisions payload and lazy-load raw JSON.
6. Collapse chart research overlays and remove the ETH comparison.
7. Remove unused optional tentacles from local profiles to eliminate startup
   error noise.
8. Reassess scalping storage after the execution-shadow cutoff on 27 September;
   preserve the frozen database but stop indefinite growth unless a new protocol
   depends on it.
9. Reassess market-observer after Carry readiness and the frozen gate sequence.
10. Stop cross-venue collection unless a new preregistered hypothesis uses it.

No persistent journal, dataset, log, archive or Docker volume was removed during
this audit.

## Cleanup applied on 2 September 2026

The conservative cleanup was applied after explicit approval:

- stopped the retired `trend-shadow`, `v5-paper` and `v5-broker` containers;
  their bind-mounted journals, reports and logs remain intact;
- kept the main KuCoin simulator and every current collector/forward observer
  running;
- replaced the default Strategy Status view with a compact **Operations** page
  containing the paper runtime, server persistence, active collectors and only
  the four current forward lines;
- added Breadth V2 and cross-venue health through new read-only mounts;
- moved rejected/retired families to a read-only **Research Archive** linked to
  `HISTORY.md` and this audit;
- reduced Decision Audit to 25 rows and moved full input/output JSON to a
  per-decision detail endpoint;
- removed the seven research/hindsight switches and the invalid ETH comparison
  from the operational landing page;
- replaced the real-trading switch with a paper-only indicator and added a
  server-side rejection for attempts to enable the real trader on local
  paper-only profiles.

Measured locally after deployment, `/strategy_status` fell from approximately
275 KB to 35 KB and `/ai_decisions` from approximately 1.72 MB to 62 KB. All
new pages returned HTTP 200 in under 50 ms on the host.

Two items remain deliberately unchanged:

- port 5001 is still published on all host interfaces because the intended
  management interface or reverse-proxy path was not established; changing it
  blindly could cut off legitimate access;
- optional upstream tentacle import warnings remain startup noise. They do not
  prevent a healthy paper runtime, and removing generated tentacles without a
  dependency audit would be riskier than leaving the warnings visible.

The legacy Compose client hit Docker's missing `ContainerConfig` compatibility
bug during the UI recreate. Only the already-stopped ephemeral main container
was removed; the replacement reused the same bind-mounted persistent data and
returned healthy. No persistent artifact or volume was deleted.
