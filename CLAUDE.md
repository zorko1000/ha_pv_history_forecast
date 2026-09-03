# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant (HACS) custom integration, domain `pv_history_forecast`, living entirely under
[custom_components/pv_history_forecast/](custom_components/pv_history_forecast/). It forecasts PV solar
yield by matching the current/forecast weather (cloud cover, UV, temperature, precipitation) against
historical days pulled from Home Assistant's own recorder database, then blending in a live PV counter
delta. There is no separate build; this directory is installed as-is into a Home Assistant instance
(via HACS or manually).

**SQLite only.** [config_flow.py](custom_components/pv_history_forecast/config_flow.py) reads the
recorder's `db_url` and hard-rejects anything not starting with `sqlite://` during setup, even though
`requirements.txt` lists `pymysql`/`psycopg2-binary` — those are unused by the config flow today.

## Commands

Run the (small) test suite:
```bash
python -m unittest discover -s tests -v
```
[tests/test_forecast_fields.py](tests/test_forecast_fields.py) is the only automated test. It loads
[forecast_fields.py](custom_components/pv_history_forecast/forecast_fields.py) directly via
`importlib.util.spec_from_file_location`, so it runs without the `homeassistant` package installed. To
run a single test: `python -m unittest tests.test_forecast_fields.ForecastFieldsTest.test_name`.

There is no linter/formatter config in the repo. CI (GitHub Actions) runs `hacs/action` (HACS repo
structure validation) and `home-assistant/actions/hassfest` — both cloud-side against `manifest.json`/
`hacs.json`, not runnable locally in a meaningful way.

To try an unreleased branch/PR against a live Home Assistant instance before it's merged (HACS can only
track releases, not branches), [scripts/deploy.sh](scripts/deploy.sh) exports `custom_components/`
from a given git ref via `git archive`, `scp`s it to `/config/custom_components/pv_history_forecast/`
over SSH, then runs `ha core restart` on the target:
```bash
scripts/deploy.sh [ref] [--host HOST] [--dry-run]   # ref defaults to HEAD, host to `homeassistant`
```
It only ships committed state (uncommitted changes are never included) and only checks the ref against
your local working tree — it has no idea what's actually installed on the target, so it can't catch a
regression against what's live. See the script's own header comment for that caveat.

[sql_integration_query_tests/](sql_integration_query_tests/) is **not** part of the automated test
suite — it's a folder of standalone `.sql`/`.py` scratch scripts used to manually test query fragments
against a copy of a real `home-assistant_v2.db`, kept for reference when editing `DEFAULT_SQL_QUERY`.

## Architecture

### Data flow (the core mechanism)

```
HA recorder DB (SQLite: states, states_meta, statistics, statistics_meta, state_attributes)
   -> DEFAULT_SQL_QUERY (const.py)              — one big query, runs at most once/hour
   -> JSON blob {pv_activity, forecast, live_hour_delta, daily_summary[...]}
   -> Jinja2 value_template (DEFAULT_VALUE_TEMPLATE / _MIN / _MAX / _TOMORROW, const.py)
   -> numeric sensor state (+ adaptive EMA smoothing for the "live" sensors)
```

The SQL query and the Jinja2 templates together *are* the forecasting algorithm; there is no separate
Python model. `daily_summary` contains, per historical day, `remaining` (from now-of-day to sunset) and
`total` (full-day) metrics for cloud/uv/temp/precip/pv_yield. The templates then: build a weighted pool
of the most similar historical days (weight = inverse of a weather-difference score, boosted by
recency), correct each day's yield for day-length/season and temperature difference, and produce a
weighted-average forecast. `PREP_AND_POOL_BUILDING` in const.py is the shared prefix reused by the
today/min/max templates; the tomorrow template duplicates similar logic against `total` instead of
`remaining` metrics.

### The two sensors most commonly used

- **`sensor.<prefix>_remaining_today`** (default prefix `pv_hist`) — the *main* entity,
  `SQLPVForecastSensor` in [sensor.py](custom_components/pv_history_forecast/sensor.py). It owns the SQL
  connection: the full query above runs once per clock hour (cached), and a cheap delta query (live PV
  counter change since the top of the hour) runs on every 5-minute `async_update`. It applies
  `DEFAULT_VALUE_TEMPLATE`, then `_apply_adaptive_ema_smoothing` to avoid abrupt jumps, with an
  unconditional reset at local midnight. It also stores the raw JSON and rendered Lovelace markdown
  (`lovelace_card_remaining_today`, `lovelace_card_tomorrow`) as state attributes — the derived sensors
  below read that cached `json` attribute instead of re-querying SQL.
- **`sensor.<prefix>_tomorrow`** — a derived entity, `PVForecastTemplateSensor` constructed with
  `no_ema=True`. It never touches SQL; it reads the main sensor's `json` attribute and applies
  `DEFAULT_VALUE_TEMPLATE_TOMORROW`, so it's a plain (unsmoothed) full-day forecast for tomorrow that
  changes only when the main sensor's hourly SQL data or the weather forecast changes.

Sibling derived sensors `_remaining_today_min` / `_remaining_today_max` (pessimistic/optimistic bounds)
follow the same derived-sensor pattern with their own templates and EMA (min has
`prevent_ema_increase=True` so it never jumps up between smoothing steps).

- **`sensor.<prefix>_today`** — `TodaySensor` in sensor.py. Not a template-derived sensor: it just adds
  the main sensor's own state (remaining forecast) to `today_actual` + `live_hour_delta`, two fields
  `DEFAULT_SQL_QUERY` writes into the cached `json` blob (`today_actual` is `pv_daily_totals.pv_yield_total`
  for today — the same statistics-based actual yield the query already computes for historical days, just
  not filtered out for "today" like `daily_summary` is). Gives a single "kWh so far + forecast" figure for
  today with the same shape as `_tomorrow`, for dashboards that want one consistent sensor per day.

### Self-tuning ("retune")

`SQLPVForecastSensor` can nightly (00:10 local time) re-search the template's weighting parameters
(`top_n`, `recency_amp`, `season_exponent`, `doy_weight`, `uv_weight`, `temp_weight`, `temp_coeff`,
`precip_weight`) via `_maybe_tune_params` / `_compute_best_retune_params` — a random-search optimizer
scored against the historical `daily_summary` pool, with results persisted across restarts (`retune_params`,
`retune_history`, `retune_seed_bank` state attributes, restored in `async_added_to_hass`). This can be
triggered manually via the `button.<prefix>_retune` entity ([button.py](custom_components/pv_history_forecast/button.py))
or the `pv_history_forecast.trigger_full_retune` / `force_retune` services (defined in
[services.yaml](custom_components/pv_history_forecast/services.yaml), handled in
[__init__.py](custom_components/pv_history_forecast/__init__.py)). Retuning is opt-out per entry
(`CONF_RETUNE`, default on).

### Other modules

- [const.py](custom_components/pv_history_forecast/const.py) — config keys, defaults, and the three
  large string constants described above (`DEFAULT_SQL_QUERY`, the `DEFAULT_VALUE_TEMPLATE*` family,
  `DEFAULT_LOVELACE_TEMPLATE_*`). Almost all "logic" changes to the forecast happen here, not in `.py`
  control flow. Comments in the SQL/templates are a mix of English and German (original author's
  working notes) — this is intentional/pre-existing style, not left over from a bad merge.
- [coordinator.py](custom_components/pv_history_forecast/coordinator.py) — `WeatherCoordinator`
  (`DataUpdateCoordinator`, 15 min interval) calls the `weather.get_forecasts` service (`type: hourly`)
  against the configured weather entity and caches the forecast list; used to kickstart entities early
  after HA restarts and to feed a diagnostic `WeatherForecastSensor`.
- [config_flow.py](custom_components/pv_history_forecast/config_flow.py) — setup/options/reconfigure
  flows. Auto-manages fixed entity IDs for cloud/UV/temperature/precipitation
  (`sensor.<prefix>_cloud_coverage` etc.) rather than letting the user pick arbitrary sensors for those;
  validates the weather entity actually supports hourly forecasts with cloud coverage before allowing
  setup to complete.
- Auto-created helper sensors in sensor.py (`CloudCoverageSensor`, `UVIndexSensor`, `TemperatureSensor`,
  `PrecipitationSensor`) mirror values out of the weather entity so Home Assistant accumulates long-term
  statistics (LTS) for them — `DEFAULT_SQL_QUERY` reads those LTS tables back in as historical input,
  falling back to raw weather-entity state before enough LTS history exists. `ForecastMethodSensor` /
  `CloudForecastSensor` are defined in sensor.py but are legacy from pre-0.3 (see README "Breaking change
  in 0.3") — check whether `async_setup_entry` still instantiates them before assuming they're live.
- [forecast_fields.py](custom_components/pv_history_forecast/forecast_fields.py) — provider-agnostic
  alias lookup (e.g. `cloud_cover` vs `cloud_coverage` vs `clouds`) for reading weather forecast dict
  fields across different weather integrations. The only module covered by automated tests.
- [weather_helper.py](custom_components/pv_history_forecast/weather_helper.py) — logs a
  `configuration.yaml` template snippet as a fallback suggestion; superseded by `coordinator.py` calling
  `weather.get_forecasts` directly, likely dead/legacy code path.

## Versioning

Bump `version` in [manifest.json](custom_components/pv_history_forecast/manifest.json) for releases;
`hacs.json` just controls HACS display (`render_readme`). `.github/workflows/release-drafter.yml` drafts
release notes from merged PRs/commits.
