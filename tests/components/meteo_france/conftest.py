"""Meteo-France generic test utils."""

from unittest.mock import patch

from meteofrance_api.model import CurrentPhenomenons, Forecast, Rain
import pytest

from homeassistant.components.meteo_france.const import (
    CONF_CITY,
    CONF_LOCATION_ENTITY,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry, load_json_object_fixture


@pytest.fixture(autouse=True)
def patch_requests():
    """Stub out services that makes requests."""
    with patch("homeassistant.components.meteo_france.MeteoFranceClient") as mock_data:
        mock_data = mock_data.return_value
        mock_data.get_forecast.return_value = Forecast(
            load_json_object_fixture("raw_forecast.json", DOMAIN)
        )
        mock_data.get_rain.return_value = Rain(
            load_json_object_fixture("raw_rain.json", DOMAIN)
        )
        mock_data.get_warning_current_phenomenons.return_value = CurrentPhenomenons(
            load_json_object_fixture("raw_warning_current_phenomenons.json", DOMAIN)
        )
        yield mock_data


@pytest.fixture(name="config_entry")
def get_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and register mock config entry."""
    entry_data = {
        CONF_CITY: "La Clusaz",
        CONF_LATITUDE: 45.90417,
        CONF_LONGITUDE: 6.42306,
    }
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        source=SOURCE_USER,
        unique_id=f"{entry_data[CONF_LATITUDE], entry_data[CONF_LONGITUDE]}",
        title=entry_data[CONF_CITY],
        data=entry_data,
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture(name="tracker")
def mock_tracker(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> er.RegistryEntry:
    """Register a device tracker located in La Clusaz."""
    entry = entity_registry.async_get_or_create(
        "device_tracker", "test", "phone", suggested_object_id="phone"
    )
    hass.states.async_set(
        entry.entity_id,
        "not_home",
        {ATTR_LATITUDE: 45.90417, ATTR_LONGITUDE: 6.42306},
    )
    return entry


@pytest.fixture(name="tracking_entry")
def mock_tracking_entry(
    hass: HomeAssistant, tracker: er.RegistryEntry
) -> MockConfigEntry:
    """Create a config entry following the device tracker."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="phone",
        unique_id=tracker.id,
        data={CONF_LOCATION_ENTITY: tracker.id},
    )
    entry.add_to_hass(hass)
    return entry
