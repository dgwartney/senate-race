# Senate Live Probability Tracker

A Streamlit dashboard that estimates each candidate's chance of winning a Senate race while votes are
still being counted. For each race, it works out the share of the uncounted vote the Democrat needs
to pass 50% of expected turnout. It then scores that share against a normal distribution centred on
the expected Democratic share of the remaining vote. A winner is projected once either side reaches
a 99.5% win probability.

Results come from a pluggable **data provider**. Out of the box you can choose built-in mock data,
civicAPI (free live results for all 35 U.S. Senate races on 3 November 2026), or any feed in this
app's own JSON format. With no configuration, the dashboard uses mock data for two races (PA-SEN and
GA-SEN).

> **Status:** the public site (`senate.dgwartney.net`) ran through election night, 3–4 November
> 2026, and was turned down on 4 November 2026. This repository has everything needed to run the
> dashboard locally or deploy your own copy.

## Requirements

- [uv](https://docs.astral.sh/uv/) (`brew install uv`), which installs Python 3.11 for you if needed
- Docker, only if you want to run the container
- The [`fly`](https://fly.io/docs/flyctl/install/) CLI and Cloudflare's
  [`wrangler`](https://developers.cloudflare.com/workers/wrangler/install-and-update/), only if you
  want to deploy it publicly

## Setup

1. Clone the repository and install the dependencies:

   ```bash
   git clone https://github.com/dgwartney/senate-race.git
   cd senate-race
   uv sync
   ```

2. Create your local configuration. Copy the example file and edit it; every setting is described
   under [Configuration](#configuration). With no `.env` at all, the dashboard runs on mock data.

   ```bash
   cp .env.example .env
   ```

   `.env` is listed in `.gitignore` and `.dockerignore`, so keys you put in it (such as `API_KEY` for
   a `json_feed` source) are never committed or copied into the Docker image. Keep secrets there or
   in your host's secret store (`fly secrets set API_KEY=...`), never in `fly.toml`.

3. Check the install by running the tests and the linter. The tests run offline.

   ```bash
   uv run pytest
   uv run ruff check
   ```

4. If you're behind a TLS-inspecting proxy such as Zscaler and want to build the Docker image, put
   its root certificate in `certs/` (see [Corporate networks](#corporate-networks-zscaler-and-similar)).

## Quick start

```bash
uv run streamlit run src/app.py
```

Open <http://localhost:8501>. The first page view starts a background poller; results appear once
its first fetch finishes (civicAPI can take 20 seconds on election night). The page then re-reads
the latest results every `REFRESH_INTERVAL_SECONDS`.

civicAPI was still serving the 3 November 2026 counts on 4 November, so `ELECTION_PROVIDER=civicapi`
shows the latest results it has.

## How it works

Fetching and rendering are separate. A background poller fetches from the data sources on its own
schedule and saves what it gets in a SQLite file. Pages only read that file, so a slow or failing
source can delay updates but can't blank the page.

```text
 Poller (one thread per kind, one poller per server) ──▶ civicAPI · OH/TX feeds · early vote
     │  fixed schedule, measured from the start of each fetch; backs off after failures
     ▼
 SQLite snapshot store   snapshots: each distinct payload, so history only grows when numbers change
                         attempts:  every fetch, successful or not
     ▲  read-only, milliseconds
 Each open page, every REFRESH_INTERVAL_SECONDS ──▶ forecast engine ──▶ page
```

- When a fetch fails, the page keeps the last good results and says when the update failed.
- An empty race list from the source counts as a failure, so it never replaces good data.
- The top of the page shows when the results were last fetched, not when the page was drawn.
- The poller restarts any of its threads that stops.

The page, top to bottom:

- **Top pane**, pinned while you scroll: data time, any warnings, and six headline numbers (contests,
  mean reporting, races led, and the control tally).
- **Map** of all 50 states, with Alaska and Hawaii as insets. States are coloured red to blue by win
  probability, tan before votes are counted, and grey where there is no Senate race.
  - Hovering a state shows a summary card.
  - Clicking a state opens its race in the details panel beside the map: who leads and by how much,
    vote-share bars, chance of winning, reporting, poll-closing time, the state's official count,
    early ballots, and a chart of the lead over the night.
  - With nothing clicked, the panel shows the closest race being counted. The **Race** box above it
    does the same job as clicking, for phones.
- **Race table** of every race, the open race first. Numbers read "—" until a race has votes.
- Collapsed sections: race cards in poll-closing order, early vote, and raw totals.

## Election night

Results arrive as each state's polls close, starting at 6 pm Eastern on 3 November. civicAPI updated
every few minutes through the 2025 governor races (New Jersey went from 26% reporting at 8:25 pm ET to
93% by midnight), and the dashboard recomputes every race on each refresh. To support that:

- Race cards are sorted by poll-closing time, with tagged races first within each time, and show
  when that state's polls close in Eastern time. Times come from `poll_closing.toml` (sources in the
  file) rather than from the data provider, because civicAPI's own times are an hour early for Eastern
  states.
- One background poller per server fetches for every viewer, so traffic to the data source doesn't
  grow with the audience.
- Until a race has votes, its card says "No votes counted yet" and the table leaves its win
  probabilities blank instead of showing the model's 50/50 starting point.

### Official state counts

For states whose election office publishes a machine-readable live feed, each race card also shows
the state's own count, linked to its results page, and flags it if the official leader differs from
the main feed's. Checked on 30 October 2026 for the seven toss-ups:

| State | Feed | Status |
|---|---|---|
| Ohio | Ohio Secretary of State JSON API | In use |
| Texas | Texas Secretary of State (Civix) JSON | In use |
| Iowa | Iowa Secretary of State (Clarity ENR) JSON | Works from home connections; its CDN challenges cloud servers, so it's off on Fly |
| Kansas | HTML page only | Not used: robots.txt disallows automated access |
| Maine | None | No statewide live results; towns report to the AP |
| Michigan | Tab-delimited file | Not used: behind a bot challenge, and no evidence it updates during the count |
| Alaska | Precinct CSV (about 5 MB) | Not used: posted a few times a night, first-choice votes only |

The feeds are polled at most once a minute for all viewers combined, identifying the dashboard in
the User-Agent. `OFFICIAL_FEEDS` picks which states to poll (default `IA,OH,TX`; `fly.toml` sets
`OH,TX`). Until a state reports votes, its line reads "no votes reported yet", because pre-election
feeds can carry test reporting figures.

### Early vote

Before results arrive, the **Early vote** panel shows ballots already cast in each Senate state (mail
ballots returned and early in-person votes), split by voters' party registration where the state
records it. This is turnout, not votes for candidates. It comes from the provider's optional
`get_early_vote()` method; civicAPI supplies it daily, and other providers simply don't show the panel.

## Data providers

The app depends only on the `ElectionDataProvider` interface in `src/providers/base.py`. A provider
has one method, `get_live_races()`, which returns a list of `RaceData`. When anything goes wrong it
raises `ProviderError`, never a library-specific exception, and the dashboard shows that error
instead of crashing. Choose a provider with `ELECTION_PROVIDER`:

| `ELECTION_PROVIDER` | Source | API key |
|---|---|---|
| `mock` | Two hard-coded races. The default when `API_ENDPOINT` is not set. | None |
| `civicapi` | [civicAPI](https://civicapi.org) live results for the 2026 U.S. Senate general elections. | None |
| `json_feed` | Any URL that returns this app's JSON format (see below). The default when `API_ENDPOINT` is set. | Optional, via `API_KEY` |

### civicAPI

civicAPI is free for personal and commercial use and needs no key. Attribution is required for
non-personal projects, and the dashboard shows it under the title. The provider makes one search
request per poll. Responses are cached for 15 seconds upstream, so keep `POLL_RACES_SECONDS` at 15
seconds or longer. A dropped connection is retried once straight away; a timeout (25 seconds) is not.

civicAPI doesn't publish an expected total vote, so the provider estimates it as counted votes ÷
`percent_reporting`. This is approximate, since the reporting figure may count precincts rather than
votes. Until a race reports more than 0%, the provider uses `CIVICAPI_FALLBACK_TURNOUT` instead.
New Hampshire's midnight-voting towns, for example, post a handful of votes at 0% reporting, and
scaling 7 votes up to a 700-vote state would make them look decisive. Before real counting starts,
every race shows about 50/50 odds, the prior.

Each race is mapped to the app's two sides by taking the leading Democrat and the leading
Republican. If a party has no candidate (for example, an independent running instead of a
Democrat), the leading other candidate fills that side.

Before votes are counted that automatic pick can't tell the nominee from a minor candidate, and
civicAPI's listings aren't always clean: in some races it keeps primary candidates or lists a
candidate twice, and its incumbent flags are unset. `candidates.toml` pins the main matchup for those
races, as `[challenger side, Republican side]` using civicAPI's candidate names:

```toml
[matchups]
"AK-SEN" = ["Mary Peltola", "Dan Sullivan"]      # three Republicans listed, Sullivan twice
"CO-SEN" = ["John Hickenlooper", "Mark Baisley"] # three Republicans listed
"ID-SEN" = ["Todd Achilles", "Jim Risch"]        # Democrat withdrew; independent challenger
"NE-SEN" = ["Dan Osborn", "Pete Ricketts"]       # no Democrat; independent challenger
```

If a pinned name disappears from civicAPI's data, that race falls back to the automatic pick.
Until any votes are counted, each race card shows "No votes counted yet" rather than the model's
50/50 starting point.

Real results start on election night. To try the pipeline before then, set `CIVICAPI_TEST_DATA=true`.
civicAPI then returns random, unrealistic counts for each race.

### Adding a provider

To add a source, such as a scraper for a state's official results page:

1. Subclass `ElectionDataProvider` in a new module under `src/providers/`. Set `name` (and
   `attribution` if the source requires it), implement `get_live_races()`, and wrap any failure in
   `ProviderError`.
2. Register a builder function for it in `PROVIDERS` in `src/providers/factory.py`.
3. Optionally override `get_early_vote()` if the source publishes early-vote data.
4. Add tests to `tests/test_providers.py`. Every registered provider is automatically checked against
   the interface.

The dashboard and the engine need no changes.

## Tagging races

`race_tags.toml` tags races so the important ones stand out. Each tag lists race IDs as they appear
on the race cards (state code + `-SEN`, e.g. `GA-SEN`), and a race can carry several tags. The file
ships with Cook Political Report's seven toss-ups (20 October 2026) and five races to watch:

```toml
[tags]
"toss-up" = ["AK-SEN", "IA-SEN", "KS-SEN", "ME-SEN", "MI-SEN", "OH-SEN", "TX-SEN"]
"watch" = ["NH-SEN", "MN-SEN", "SC-SEN", "NC-SEN", "NE-SEN"]

[control]
tag = "toss-up"
dem_needed = 4
rep_needed = 4
```

The dashboard then:

- shows each race's tags as coloured badges on its card
- lists tagged races first
- shows tags in the map's hover cards and the details panel
- with a `[control]` section, adds a tally of how many races with that tag each party leads, against
  the number it needs

Add or rename tags freely; the file is re-read on every page load. If the file has an error, the
dashboard shows a warning and runs without tags. Use `RACE_TAGS_FILE` to point at a different file.

## Configuration

The app reads these environment variables, and also loads them from a `.env` file in the project root:

| Variable | Default | Purpose |
|---|---|---|
| `ELECTION_PROVIDER` | *(empty)* | `mock`, `civicapi` or `json_feed`. When empty: `json_feed` if `API_ENDPOINT` is set, otherwise `mock`. |
| `REFRESH_INTERVAL_SECONDS` | `30` | Seconds between each page re-reading the latest results. |
| `POLL_RACES_SECONDS` | `30` | Seconds between race-result fetches, measured from the start of each fetch. |
| `POLL_OFFICIALS_SECONDS` | `60` | Seconds between official state feed fetches. |
| `POLL_EARLY_VOTE_SECONDS` | `3600` | Seconds between early-vote fetches. |
| `SNAPSHOT_DB` | `data/snapshots.db` | SQLite file the poller writes and pages read. On Fly it is on the container disk, so a restart empties it until the next fetch. |
| `POLL_CLOSING_FILE` | `poll_closing.toml` | Poll-closing times file. |
| `SOURCES_FILE` | `sources.toml` | Preferred results source per state: the state's own feed (`official`, also needs `OFFICIAL_FEEDS`) or civicAPI. Falls back to civicAPI when the state feed fails. |
| `API_ENDPOINT` | *(empty)* | `json_feed` only: URL of the feed. |
| `API_KEY` | *(empty)* | `json_feed` only: sent as `Authorization: Bearer <key>` when set. |
| `CIVICAPI_ELECTION_DATE` | `2026-11-03` | `civicapi` only: election date to search. |
| `CIVICAPI_RACE_TYPE` | `US Senate` | `civicapi` only: race type to search for (civicAPI `type` filter). |
| `CIVICAPI_TEST_DATA` | `false` | `civicapi` only: `true` to use civicAPI's random test counts. |
| `CIVICAPI_FALLBACK_TURNOUT` | `1000000` | `civicapi` only: placeholder turnout used before any votes are counted. |
| `CIVICAPI_MATCHUPS_FILE` | `candidates.toml` | `civicapi` only: pinned matchups, relative to the project root. |
| `OFFICIAL_FEEDS` | `IA,OH,TX` | Official state feeds to show as a cross-check (comma-separated state codes; empty for none). |
| `RACE_TAGS_FILE` | `race_tags.toml` | Race tags file, relative to the project root. |

Example `.env` for live civicAPI results:

```bash
ELECTION_PROVIDER=civicapi
REFRESH_INTERVAL_SECONDS=30
```

### JSON feed format

A `json_feed` URL must return JSON shaped like this. `prior_dem_share` defaults to `0.50` and `uncertainty_sd`
to `0.035` when left out:

```json
{
  "races": [
    {
      "race_id": "PA-SEN",
      "state": "Pennsylvania",
      "dem_name": "Democrat",
      "dem_votes": 1420000,
      "rep_name": "Republican",
      "rep_votes": 1390000,
      "expected_turnout": 3200000,
      "prior_dem_share": 0.53,
      "uncertainty_sd": 0.03
    }
  ]
}
```

## Managing dependencies

The project uses `uv`. `pyproject.toml` lists the dependencies, and `uv.lock` pins the exact versions.
There is no `requirements.txt`.

| Task | Command |
|---|---|
| Install or refresh the environment | `uv sync` |
| Add a dependency | `uv add <package>` |
| Remove a dependency | `uv remove <package>` |
| Upgrade the locked versions | `uv lock --upgrade`, then `uv sync` |
| Run any command in the environment | `uv run <command>` |
| Run the tests | `uv run pytest` (with coverage: `uv run pytest --cov=src`) |
| Lint, including docstrings | `uv run ruff check` |

Commit `uv.lock` whenever it changes, because the Docker build fails if the lock file is out of date.

## Docker

```bash
docker compose up --build
```

The image uses Astral's `uv` image with Python 3.11 and installs the dependencies with
`uv sync --locked`. The app is served on <http://localhost:8501>.

`.dockerignore` keeps `.env` out of the image, and `docker-compose.yml` sets only
`REFRESH_INTERVAL_SECONDS`, so the container uses mock data. To use live data, add
`ELECTION_PROVIDER=civicapi` (or the `json_feed` settings) under `environment:` in
`docker-compose.yml`, or add `env_file: .env` to the service.

## Deploying your own copy (Fly.io + Cloudflare)

The original site ran on Fly.io as the app `senate-race-tracker` (one always-on machine in `sjc`,
live civicAPI data), served on a custom domain through a Cloudflare Worker that proxies every
request, including Streamlit's WebSocket, to the Fly hostname. It was turned down on 4 November
2026 by scaling the Fly app to zero machines and deleting the Worker. To run your own:

1. **Create the Fly app.** Fly app names are global, so pick your own and set it as `app` in
   `fly.toml` (and `FLY_APP` for `deploy/snapshots.sh`). Non-secret settings go under `[env]`;
   secrets such as `API_KEY` go in Fly's secret store, never in `fly.toml`:

   ```bash
   fly auth login
   fly apps create <your-app-name>
   fly secrets set API_KEY=...        # only for a json_feed source that needs a key
   fly deploy --remote-only
   ```

   The app is then live at `https://<your-app-name>.fly.dev`.

2. **Optional: serve it on your own domain with Cloudflare.** You need a zone (domain) in your
   Cloudflare account. In `deploy/cloudflare/wrangler.toml`, set `pattern` to the hostname you
   want; in `deploy/cloudflare/worker.js`, set `ORIGIN` to your Fly hostname. Then:

   ```bash
   wrangler login                     # or export CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN
   cd deploy/cloudflare && wrangler deploy
   ```

   The Worker's `custom_domain` route makes Cloudflare create the DNS record and certificate, so no
   manual DNS changes are needed. If the hostname doesn't resolve a minute later, re-attach it under
   **Workers & Pages → your Worker → Settings → Domains & Routes**. The Worker rewrites the `Origin`
   header to the Fly hostname, because Streamlit rejects WebSocket connections from a different
   origin.

3. **Optional: identify yourself to the official state feeds.** `USER_AGENT` in `src/officials.py`
   links to this repository; point it at your own site or repository.

| Task | Command |
|---|---|
| Deploy a new version of the app | `fly deploy --remote-only` |
| App status and logs | `fly status`, `fly logs` |
| Back up or restore the results database around a deploy | `deploy/snapshots.sh backup` / `restore` (see `deploy/RUNBOOK.md`) |
| Deploy the Cloudflare Worker (and its custom domain) | `cd deploy/cloudflare && wrangler deploy` |
| Turn the site down, keeping the Fly app | `fly scale count 0`, then `wrangler delete --name senate-dashboard-proxy` |
| Bring it back up | `fly scale count 1`, then `wrangler deploy` |
| Remove the Fly app completely | `fly apps destroy <your-app-name>` |

The results database lives on the machine's temporary disk, so scaling to zero erases it. Run
`deploy/snapshots.sh backup` first if you want to keep the night's history.

## Corporate networks (Zscaler and similar)

Proxies that inspect TLS, such as Zscaler, re-sign HTTPS traffic with their own root certificate.
The operating system trusts that root, but Python's bundled certificate list does not, so requests
fail with `CERTIFICATE_VERIFY_FAILED`. The app calls `truststore.inject_into_ssl()` at startup, so
Python uses the operating system's certificate store and works behind these proxies with no extra
setup on a Mac where Zscaler is installed.

Anything that doesn't read the operating system's store needs the root certificate as a file in
`certs/`. Certificates there are not committed (`.gitignore` excludes `certs/*.crt`), so export
your own, for example the Zscaler root from the macOS keychain:

```bash
security find-certificate -c "Zscaler Root CA" -p /Library/Keychains/System.keychain > certs/zscaler-root-ca.crt
```

- **Docker:** the image copies every `*.crt` file in `certs/` into its system store and points
  Python and `uv` at it, so both the build and the running app work behind Zscaler. Off a Zscaler
  network the extra root does no harm, and you can leave `certs/` empty.
- **Other tools on your Mac:** point them at the file, for example
  `export REQUESTS_CA_BUNDLE=$PWD/certs/zscaler-root-ca.crt` for scripts that use `requests` without
  `truststore`.

## Project layout

| Path | Contents |
|---|---|
| `src/app.py` | Entry point. Starts the services once per server and renders the page from the store. |
| `src/config.py` | `Settings`: every environment variable in one place. |
| `src/poller.py` | Background `Poller` and the standard fetch jobs. |
| `src/store.py` | `SnapshotStore`: the SQLite store between poller and pages. |
| `src/live.py` | `LiveDataReader` (latest data and freshness notices) and `MarginHistory`. |
| `src/providers/base.py` | The `ElectionDataProvider` interface and `ProviderError`. |
| `src/providers/factory.py` | `create_provider()` and the `PROVIDERS` registry. |
| `src/providers/mock.py`, `civicapi.py`, `json_feed.py` | The built-in providers. |
| `src/engine.py` | Win-probability model. |
| `src/models.py` | Race, candidate, forecast and notice data classes. |
| `src/geo.py` | State codes and names. |
| `src/officials.py` | Official state results feeds (Iowa, Ohio, Texas). |
| `src/schedule.py` | Loads `poll_closing.toml`. |
| `src/tags.py` | Loads `race_tags.toml`. |
| `src/ui/components.py` | Page sections: top pane, map and details panel, race table, expanders. |
| `src/ui/usmap.py` | The map and its hover cards. |
| `src/ui/charts.py` | The lead-over-the-night chart. |
| `src/ui/format.py`, `theme.py` | Text formatting, colours and page CSS. |
| `candidates.toml` | Pinned civicAPI matchups for ambiguous races. |
| `poll_closing.toml` | Poll-closing times per state, with sources. |
| `race_tags.toml` | Race tags and the control tally settings. |
| `tests/` | Unit tests for every module, plus whole-page Streamlit tests. These run offline against fake HTTP responses. |
| `.env.example` | Template for your local `.env`. |
| `fly.toml` | Fly.io app configuration. |
| `deploy/RUNBOOK.md`, `snapshots.sh`, `restore_snapshots.py` | Backing up and restoring the results database around a deploy. |
| `deploy/cloudflare/` | Cloudflare Worker that serves the custom domain. |
| `certs/` | Extra root CAs trusted inside the Docker image (Zscaler). Empty in the repository. |
