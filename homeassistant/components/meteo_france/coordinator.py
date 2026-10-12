"""Support for Meteo-France weather data."""

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import override

from meteofrance_api.client import MeteoFranceClient
from meteofrance_api.model import CurrentPhenomenons, Forecast, Rain

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, EntityStateAttribute
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import (
    async_track_entity_registry_updated_event,
    async_track_state_change_event,
)
from homeassistant.helpers.location import has_location
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util, location as location_util

from .const import CONF_LOCATION_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)

type MeteoFranceConfigEntry = ConfigEntry[MeteoFranceData]


@dataclass
class MeteoFranceData:
    """Data for the Meteo-France integration."""

    forecast_coordinator: MeteoFranceForecastUpdateCoordinator
    rain_coordinator: MeteoFranceRainUpdateCoordinator | None
    alert_coordinator: MeteoFranceAlertUpdateCoordinator | None


SCAN_INTERVAL_RAIN = timedelta(minutes=5)
SCAN_INTERVAL = timedelta(minutes=15)

LOCATION_RELOAD_COOLDOWN = timedelta(minutes=15)
# Meters away from the position the loaded entry uses
LOCATION_CHANGE_THRESHOLD = 5000
LOCATION_DRIFT_THRESHOLD = 1000


@callback
def async_get_location(
    hass: HomeAssistant, entry: MeteoFranceConfigEntry
) -> tuple[float, float, str | None]:
    """Return the coordinates to use and the tracked entity id, if any."""
    if (registry_id := entry.data.get(CONF_LOCATION_ENTITY)) is None:
        return entry.data[CONF_LATITUDE], entry.data[CONF_LONGITUDE], None

    if (entity_entry := er.async_get(hass).async_get(registry_id)) is None:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="entity_not_found"
        )
    if entity_entry.disabled_by is not None:
        raise ConfigEntryError(
            translation_domain=DOMAIN, translation_key="entity_disabled"
        )
    state = hass.states.get(entity_entry.entity_id)
    if state is None or not has_location(state):
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="entity_unavailable",
            translation_placeholders={"entity_id": entity_entry.entity_id},
        )
    return (
        state.attributes[EntityStateAttribute.LATITUDE],
        state.attributes[EntityStateAttribute.LONGITUDE],
        entity_entry.entity_id,
    )


def get_unique_id_prefix(entry: ConfigEntry | None) -> str | None:
    """Return a position-independent unique id prefix for tracking entries."""
    if entry is not None and CONF_LOCATION_ENTITY in entry.data:
        return entry.entry_id
    return None


class MeteoFranceForecastUpdateCoordinator(DataUpdateCoordinator[Forecast]):
    """Coordinator for Meteo-France forecast data."""

    config_entry: MeteoFranceConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoFranceConfigEntry,
        client: MeteoFranceClient,
        latitude: float,
        longitude: float,
        location_entity_id: str | None = None,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Météo-France forecast for city {entry.title}",
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self._client = client
        self._latitude = latitude
        self._longitude = longitude
        self._location_entity_id = location_entity_id
        self._loaded_at = dt_util.utcnow()

    @callback
    def async_track_location(self) -> None:
        """Reload the entry when the tracked entity moves or changes."""
        assert self._location_entity_id is not None

        @callback
        def _async_on_state_change(_: Event[EventStateChangedData]) -> None:
            # Moves ignored during the cooldown are caught by the next refresh
            if dt_util.utcnow() - self._loaded_at >= LOCATION_RELOAD_COOLDOWN:
                self._async_reload_if_moved(LOCATION_CHANGE_THRESHOLD)

        @callback
        def _async_on_registry_update(
            event: Event[er.EventEntityRegistryUpdatedData],
        ) -> None:
            if event.data["action"] == "remove" or (
                event.data["action"] == "update"
                and (
                    "entity_id" in event.data["changes"]
                    or "disabled_by" in event.data["changes"]
                )
            ):
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )

        self.config_entry.async_on_unload(
            async_track_state_change_event(
                self.hass, self._location_entity_id, _async_on_state_change
            )
        )
        self.config_entry.async_on_unload(
            async_track_entity_registry_updated_event(
                self.hass, self._location_entity_id, _async_on_registry_update
            )
        )

    @callback
    def _async_reload_if_moved(self, threshold: float) -> None:
        """Reload the entry if the tracked entity moved beyond the threshold."""
        assert self._location_entity_id is not None
        state = self.hass.states.get(self._location_entity_id)
        if state is None or not has_location(state):
            return
        distance = location_util.distance(
            self._latitude,
            self._longitude,
            state.attributes[EntityStateAttribute.LATITUDE],
            state.attributes[EntityStateAttribute.LONGITUDE],
        )
        if distance is not None and distance > threshold:
            _LOGGER.debug(
                "%s moved %.0f m, reloading %s",
                self._location_entity_id,
                distance,
                self.config_entry.title,
            )
            self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    @override
    async def _async_update_data(self) -> Forecast:
        """Get data from Meteo-France forecast."""
        if self._location_entity_id is not None:
            self._async_reload_if_moved(LOCATION_DRIFT_THRESHOLD)
        return await self.hass.async_add_executor_job(
            self._client.get_forecast, self._latitude, self._longitude
        )


class MeteoFranceRainUpdateCoordinator(DataUpdateCoordinator[Rain]):
    """Coordinator for Meteo-France rain data."""

    config_entry: MeteoFranceConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoFranceConfigEntry,
        client: MeteoFranceClient,
        latitude: float,
        longitude: float,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Météo-France rain for city {entry.title}",
            config_entry=entry,
            update_interval=SCAN_INTERVAL_RAIN,
        )
        self._client = client
        self._latitude = latitude
        self._longitude = longitude

    @override
    async def _async_update_data(self) -> Rain:
        """Get data from Meteo-France rain."""
        return await self.hass.async_add_executor_job(
            self._client.get_rain, self._latitude, self._longitude
        )


class MeteoFranceAlertUpdateCoordinator(DataUpdateCoordinator[CurrentPhenomenons]):
    """Coordinator for Meteo-France alert data."""

    config_entry: MeteoFranceConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: MeteoFranceConfigEntry,
        client: MeteoFranceClient,
        department: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Météo-France alert for department {department}",
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self._client = client
        self._department = department

    @override
    async def _async_update_data(self) -> CurrentPhenomenons:
        """Get data from Meteo-France alert."""
        return await self.hass.async_add_executor_job(
            self._client.get_warning_current_phenomenons, self._department, 0, True
        )
