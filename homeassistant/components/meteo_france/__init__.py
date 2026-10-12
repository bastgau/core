"""Support for Meteo-France weather data."""

import logging

from meteofrance_api.client import MeteoFranceClient
from meteofrance_api.helpers import is_valid_warning_department
from requests import RequestException

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_LOCATION_ENTITY, METEO_FRANCE_DATA, PLATFORMS
from .coordinator import (
    MeteoFranceAlertUpdateCoordinator,
    MeteoFranceConfigEntry,
    MeteoFranceData,
    MeteoFranceForecastUpdateCoordinator,
    MeteoFranceRainUpdateCoordinator,
    async_get_location,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: MeteoFranceConfigEntry) -> bool:
    """Set up a Meteo-France account from a config entry."""
    if (departments_with_alert := hass.data.get(METEO_FRANCE_DATA)) is None:
        departments_with_alert = hass.data[METEO_FRANCE_DATA] = set()

    client = MeteoFranceClient()

    latitude, longitude, location_entity_id = async_get_location(hass, entry)
    coordinator_forecast = MeteoFranceForecastUpdateCoordinator(
        hass, entry, client, latitude, longitude, location_entity_id
    )
    coordinator_rain = None
    coordinator_alert = None

    # Fetch initial data so we have data when entities subscribe
    await coordinator_forecast.async_refresh()

    if not coordinator_forecast.last_update_success:
        raise ConfigEntryNotReady

    # Check rain forecast.
    coordinator_rain = MeteoFranceRainUpdateCoordinator(
        hass, entry, client, latitude, longitude
    )
    try:
        await coordinator_rain._async_refresh(log_failures=False)  # noqa: SLF001
    except RequestException:
        _LOGGER.warning(
            "1 hour rain forecast not available: %s is not in covered zone",
            entry.title,
        )

    department = coordinator_forecast.data.position.get("dept")
    _LOGGER.debug(
        "Department corresponding to %s is %s",
        entry.title,
        department,
    )
    if department is not None and is_valid_warning_department(department):
        # Tracking entries have entry-scoped alert unique ids, so they skip the lock
        if location_entity_id or department not in departments_with_alert:
            coordinator_alert = MeteoFranceAlertUpdateCoordinator(
                hass,
                entry,
                client,
                department,
            )

            await coordinator_alert.async_refresh()

            if coordinator_alert.last_update_success and not location_entity_id:
                departments_with_alert.add(department)
        else:
            _LOGGER.warning(
                (
                    "Weather alert for department %s won't be added with city %s, as it"
                    " has already been added within another city"
                ),
                department,
                entry.title,
            )
    else:
        _LOGGER.warning(
            (
                "Weather alert not available: The city %s is not in metropolitan France"
                " or Andorre"
            ),
            entry.title,
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if coordinator_rain and not coordinator_rain.last_update_success:
        coordinator_rain = None
    if coordinator_alert and not coordinator_alert.last_update_success:
        coordinator_alert = None
    entry.runtime_data = MeteoFranceData(
        forecast_coordinator=coordinator_forecast,
        rain_coordinator=coordinator_rain,
        alert_coordinator=coordinator_alert,
    )

    if location_entity_id:
        coordinator_forecast.async_track_location()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: MeteoFranceConfigEntry
) -> bool:
    """Unload a config entry."""
    if entry.runtime_data.alert_coordinator and CONF_LOCATION_ENTITY not in entry.data:
        department = entry.runtime_data.forecast_coordinator.data.position.get("dept")
        hass.data[METEO_FRANCE_DATA].discard(department)
        _LOGGER.debug(
            (
                "Weather alert for depatment %s unloaded and released. It can be added"
                " now by another city"
            ),
            department,
        )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Another entry may already have removed the shared registry
    if unload_ok and not hass.data.get(METEO_FRANCE_DATA):
        hass.data.pop(METEO_FRANCE_DATA, None)

    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: MeteoFranceConfigEntry
) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)
