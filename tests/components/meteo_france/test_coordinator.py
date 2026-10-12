"""Tests for Météo-France coordinators following a location entity."""

from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, call

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components.meteo_france.const import CONF_LOCATION_ENTITY, DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_LATITUDE, ATTR_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry, async_fire_time_changed

TRACKER_ENTITY_ID = "device_tracker.phone"
LATITUDE = 45.90417
LONGITUDE = 6.42306
# Roughly 111 km per degree of latitude
LATITUDE_500_M = LATITUDE + 0.0045
LATITUDE_2_KM = LATITUDE + 0.018
LATITUDE_4_KM = LATITUDE + 0.036
LATITUDE_4_5_KM = LATITUDE + 0.0405
LATITUDE_6_KM = LATITUDE + 0.054
LATITUDE_12_KM = LATITUDE + 0.108
LATITUDE_18_KM = LATITUDE + 0.162


def _location(latitude: float) -> dict[str, float]:
    """Return location attributes at the given latitude."""
    return {ATTR_LATITUDE: latitude, ATTR_LONGITUDE: LONGITUDE}


@pytest.fixture(name="broken_entities")
def mock_broken_entities(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> dict[str, str]:
    """Register unusable location entities and map their entity id to registry id."""
    disabled = entity_registry.async_get_or_create(
        "device_tracker",
        "test",
        "disabled",
        suggested_object_id="disabled",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    no_location = entity_registry.async_get_or_create(
        "device_tracker", "test", "no_location", suggested_object_id="no_location"
    )
    hass.states.async_set(no_location.entity_id, "home")
    removed = entity_registry.async_get_or_create(
        "device_tracker", "test", "removed", suggested_object_id="removed"
    )
    entity_registry.async_remove(removed.entity_id)
    return {
        disabled.entity_id: disabled.id,
        no_location.entity_id: no_location.id,
        removed.entity_id: removed.id,
    }


async def _async_setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the entry and check it loaded."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_setup(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    patch_requests: MagicMock,
    tracking_entry: MockConfigEntry,
) -> None:
    """Test the entry uses the entity location and position-independent ids."""
    await _async_setup(hass, tracking_entry)

    assert patch_requests.get_forecast.call_args == call(LATITUDE, LONGITUDE)
    assert patch_requests.get_rain.call_args == call(LATITUDE, LONGITUDE)
    unique_ids = {
        entity.unique_id
        for entity in er.async_entries_for_config_entry(
            entity_registry, tracking_entry.entry_id
        )
    }
    assert tracking_entry.entry_id in unique_ids
    assert f"{tracking_entry.entry_id}_temperature" in unique_ids
    assert f"{tracking_entry.entry_id}_weather_alert" in unique_ids
    assert all(uid.startswith(tracking_entry.entry_id) for uid in unique_ids)


@pytest.mark.parametrize(
    ("entity_id", "expected_state"),
    [
        pytest.param(
            "device_tracker.no_location",
            ConfigEntryState.SETUP_RETRY,
            id="no_location",
        ),
        pytest.param(
            "device_tracker.disabled", ConfigEntryState.SETUP_ERROR, id="disabled"
        ),
        pytest.param(
            "device_tracker.removed", ConfigEntryState.SETUP_ERROR, id="removed"
        ),
    ],
)
async def test_setup_unusable_entity(
    hass: HomeAssistant,
    broken_entities: dict[str, str],
    entity_id: str,
    expected_state: ConfigEntryState,
) -> None:
    """Test setup fails when the location entity cannot be used."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=broken_entities[entity_id],
        data={CONF_LOCATION_ENTITY: broken_entities[entity_id]},
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is expected_state


def _forecast_latitudes(client: MagicMock) -> set[float]:
    """Return the latitudes forecasts were requested for."""
    return {args[0] for args, _ in client.get_forecast.call_args_list}


@pytest.mark.parametrize(
    ("attributes", "expected_latitudes"),
    [
        pytest.param(_location(LATITUDE_500_M), {LATITUDE}, id="small_move"),
        pytest.param(
            _location(LATITUDE_4_5_KM), {LATITUDE, LATITUDE_4_5_KM}, id="drift"
        ),
        pytest.param({}, {LATITUDE}, id="no_location"),
    ],
)
async def test_refresh_reloads_after_drift(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    entity_registry: er.EntityRegistry,
    patch_requests: MagicMock,
    tracking_entry: MockConfigEntry,
    attributes: dict[str, Any],
    expected_latitudes: set[float],
) -> None:
    """Test moves below the immediate threshold are applied on the next refresh."""
    await _async_setup(hass, tracking_entry)
    entities = er.async_entries_for_config_entry(
        entity_registry, tracking_entry.entry_id
    )

    hass.states.async_set(TRACKER_ENTITY_ID, "not_home", attributes)
    await hass.async_block_till_done()
    assert _forecast_latitudes(patch_requests) == {LATITUDE}

    # Refresh is scheduled on a truncated loop time plus jitter, so go past it
    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert tracking_entry.state is ConfigEntryState.LOADED
    assert _forecast_latitudes(patch_requests) == expected_latitudes
    assert (
        er.async_entries_for_config_entry(entity_registry, tracking_entry.entry_id)
        == entities
    )


@pytest.mark.parametrize(
    ("latitudes", "expected_latitudes"),
    [
        pytest.param([LATITUDE_4_KM], {LATITUDE}, id="small_move"),
        pytest.param([LATITUDE_6_KM], {LATITUDE, LATITUDE_6_KM}, id="large_move"),
        pytest.param(
            [LATITUDE_2_KM, LATITUDE_4_KM, LATITUDE_6_KM],
            {LATITUDE, LATITUDE_6_KM},
            id="small_moves_adding_up",
        ),
    ],
)
async def test_large_move_reloads_immediately(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    patch_requests: MagicMock,
    tracking_entry: MockConfigEntry,
    latitudes: list[float],
    expected_latitudes: set[float],
) -> None:
    """Test moves adding up beyond the threshold reload without waiting a refresh."""
    # Without polling, only location changes can trigger a reload
    hass.config_entries.async_update_entry(tracking_entry, pref_disable_polling=True)
    await _async_setup(hass, tracking_entry)
    freezer.tick(timedelta(minutes=16))

    for latitude in latitudes:
        hass.states.async_set(TRACKER_ENTITY_ID, "not_home", _location(latitude))
        await hass.async_block_till_done()

    assert _forecast_latitudes(patch_requests) == expected_latitudes


async def test_large_move_waits_for_cooldown(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    patch_requests: MagicMock,
    tracking_entry: MockConfigEntry,
) -> None:
    """Test a large move right after loading is applied on the next refresh."""
    await _async_setup(hass, tracking_entry)

    hass.states.async_set(TRACKER_ENTITY_ID, "not_home", _location(LATITUDE_6_KM))
    await hass.async_block_till_done()
    assert _forecast_latitudes(patch_requests) == {LATITUDE}

    freezer.tick(timedelta(minutes=16))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert _forecast_latitudes(patch_requests) == {LATITUDE, LATITUDE_6_KM}


async def test_fast_moves_reload_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    patch_requests: MagicMock,
    tracking_entry: MockConfigEntry,
) -> None:
    """Test a quick journey triggers a single reload within the cooldown."""
    # Without polling, only location changes can trigger a reload
    hass.config_entries.async_update_entry(tracking_entry, pref_disable_polling=True)
    await _async_setup(hass, tracking_entry)
    freezer.tick(timedelta(minutes=16))

    for latitude in (LATITUDE_6_KM, LATITUDE_12_KM, LATITUDE_18_KM):
        hass.states.async_set(TRACKER_ENTITY_ID, "not_home", _location(latitude))
        await hass.async_block_till_done()
        freezer.tick(timedelta(minutes=2))

    assert _forecast_latitudes(patch_requests) == {LATITUDE, LATITUDE_6_KM}


async def test_entity_removed(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    tracking_entry: MockConfigEntry,
) -> None:
    """Test removing the location entity reloads the entry into an error."""
    await _async_setup(hass, tracking_entry)

    entity_registry.async_remove(TRACKER_ENTITY_ID)
    await hass.async_block_till_done()

    assert tracking_entry.state is ConfigEntryState.SETUP_ERROR
