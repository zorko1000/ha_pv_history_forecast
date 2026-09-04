import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest


COMPONENT_DIR = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "pv_history_forecast"
)
DOMAIN = "pv_history_forecast"

# energy.py imports `.const`, so it can only be loaded as part of a package.
# Stub that package (and const) instead of importing the real one, which would
# drag in homeassistant -- the same "runs without HA installed" constraint the
# forecast_fields test works under.
PKG = "pv_history_forecast_energy_test_pkg"
_pkg = types.ModuleType(PKG)
_pkg.__path__ = [str(COMPONENT_DIR)]
_const = types.ModuleType(f"{PKG}.const")
_const.DOMAIN = DOMAIN
sys.modules[PKG] = _pkg
sys.modules[f"{PKG}.const"] = _const

SPEC = importlib.util.spec_from_file_location(f"{PKG}.energy", COMPONENT_DIR / "energy.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[f"{PKG}.energy"] = MODULE
SPEC.loader.exec_module(MODULE)

build_wh_hours = MODULE.build_wh_hours
async_get_solar_forecast = MODULE.async_get_solar_forecast


class FakeHass:
    def __init__(self, data):
        self.data = data


class FakeHourlySensor:
    def __init__(self, forecast_entries):
        self.forecast_entries = forecast_entries


def _hass_with_sensor(entry_id, forecast_entries):
    return FakeHass({DOMAIN: {entry_id: {"hourly_sensor": FakeHourlySensor(forecast_entries)}}})


ENTRIES = [
    {"start": "2026-09-04T10:00:00+02:00", "end": "2026-09-04T11:00:00+02:00", "value": 1200},
    {"start": "2026-09-04T11:00:00+02:00", "end": "2026-09-04T12:00:00+02:00", "value": 0},
]


class BuildWhHoursTest(unittest.TestCase):
    def test_maps_start_to_value_keeping_zero_hours(self) -> None:
        self.assertEqual(
            build_wh_hours(ENTRIES),
            {
                "2026-09-04T10:00:00+02:00": 1200.0,
                "2026-09-04T11:00:00+02:00": 0.0,
            },
        )

    def test_skips_malformed_entries(self) -> None:
        entries = [
            "not a dict",
            {"end": "2026-09-04T11:00:00+02:00", "value": 500},  # no start
            {"start": "2026-09-04T12:00:00+02:00"},  # no value
            {"start": "2026-09-04T13:00:00+02:00", "value": "n/a"},  # not numeric
            {"start": "2026-09-04T14:00:00+02:00", "value": 750},
        ]

        self.assertEqual(build_wh_hours(entries), {"2026-09-04T14:00:00+02:00": 750.0})

    def test_empty_input(self) -> None:
        self.assertEqual(build_wh_hours(None), {})
        self.assertEqual(build_wh_hours([]), {})


class AsyncGetSolarForecastTest(unittest.TestCase):
    def test_returns_wh_hours_for_known_entry(self) -> None:
        hass = _hass_with_sensor("entry-1", ENTRIES)

        result = asyncio.run(async_get_solar_forecast(hass, "entry-1"))

        self.assertEqual(
            result,
            {
                "wh_hours": {
                    "2026-09-04T10:00:00+02:00": 1200.0,
                    "2026-09-04T11:00:00+02:00": 0.0,
                }
            },
        )

    def test_returns_none_for_unknown_entry(self) -> None:
        hass = _hass_with_sensor("entry-1", ENTRIES)

        self.assertIsNone(asyncio.run(async_get_solar_forecast(hass, "other-entry")))

    def test_returns_none_before_the_sensor_is_registered(self) -> None:
        self.assertIsNone(asyncio.run(async_get_solar_forecast(FakeHass({}), "entry-1")))

    def test_returns_none_while_the_sensor_has_no_series_yet(self) -> None:
        hass = _hass_with_sensor("entry-1", [])

        self.assertIsNone(asyncio.run(async_get_solar_forecast(hass, "entry-1")))


if __name__ == "__main__":
    unittest.main()
