"""Keep manual device links alive across restarts and reloads.

An entity platform passes ``device_id=device.id if device else None`` on every add
(``homeassistant/helpers/entity_platform.py``), so the owning integration resets a
manually set device link whenever it re-adds the entity. The links recorded here are
re-applied at startup and whenever the registry clears one of them.
"""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.start import async_at_started

from .const import CONF_LINKS, LOGGER, REAPPLY_FAILURE_LOG_LIMIT
from .helpers import (
    Identifiers,
    as_pairs,
    async_resolve_device,
    async_set_device_link,
    format_identifiers,
)

type DeviceLinkToolsConfigEntry = ConfigEntry[DeviceLinkReapplier]


class DeviceLinkReapplier:
    """Re-apply the device links the owning integrations reset."""

    def __init__(self, hass: HomeAssistant, entry: DeviceLinkToolsConfigEntry) -> None:
        """Initialize from the links stored in the config entry options."""
        self.hass = hass
        self.entry = entry
        self._links: dict[str, Identifiers] = {
            entity_id: {(pair[0], pair[1]) for pair in pairs}
            for entity_id, pairs in entry.options.get(CONF_LINKS, {}).items()
        }
        self._failures: dict[str, int] = {}

    @callback
    def async_setup(self) -> None:
        """Start watching for links that need to be re-applied."""
        self.entry.async_on_unload(async_at_started(self.hass, self._async_at_started))
        self.entry.async_on_unload(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._handle_registry_updated,
                event_filter=self._filter_registry_updated,
            )
        )

    @callback
    def async_track(self, entity_ids: list[str], identifiers: Identifiers) -> None:
        """Record the device link of entities so it can be re-applied."""
        for entity_id in entity_ids:
            self._links[entity_id] = identifiers
            self._failures.pop(entity_id, None)
        self._async_save()

    @callback
    def async_forget(self, entity_ids: list[str]) -> None:
        """Stop re-applying the device link of entities."""
        forgotten = [
            entity_id
            for entity_id in entity_ids
            if self._links.pop(entity_id, None) is not None
        ]
        if not forgotten:
            return
        for entity_id in forgotten:
            self._failures.pop(entity_id, None)
        self._async_save()

    @callback
    def _async_save(self) -> None:
        links = {
            entity_id: as_pairs(identifiers)
            for entity_id, identifiers in sorted(self._links.items())
        }
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_LINKS: links}
        )

    @callback
    def _async_at_started(self, hass: HomeAssistant) -> None:
        """Re-apply every recorded link once the integrations have set up."""
        entity_registry = er.async_get(hass)
        stale = [
            entity_id
            for entity_id in self._links
            if entity_registry.async_get(entity_id) is None
        ]
        if stale:
            self.async_forget(stale)
        for entity_id in list(self._links):
            self._async_reapply(entity_id)

    @callback
    def _filter_registry_updated(self, data: Any) -> bool:
        """Only wake up for a tracked entity whose id or device link changed."""
        if data["action"] == "remove":
            return data["entity_id"] in self._links
        if data["action"] != "update":
            return False
        changes = data["changes"]
        return ("device_id" in changes or "entity_id" in changes) and (
            data["entity_id"] in self._links or data.get("old_entity_id") in self._links
        )

    @callback
    def _handle_registry_updated(self, event: Event[Any]) -> None:
        """Schedule the work outside of the registry update being observed."""
        data = event.data
        if data["action"] == "remove":
            self.hass.loop.call_soon(self._async_forget_removed, data["entity_id"])
        elif (old_entity_id := data.get("old_entity_id")) is not None:
            self.hass.loop.call_soon(
                self._async_rename, old_entity_id, data["entity_id"]
            )
        else:
            self.hass.loop.call_soon(self._async_reapply, data["entity_id"])

    @callback
    def _async_forget_removed(self, entity_id: str) -> None:
        """Drop the link of an entity that left the registry."""
        if self._links.pop(entity_id, None) is not None:
            self._failures.pop(entity_id, None)
            self._async_save()

    @callback
    def _async_rename(self, old_entity_id: str, entity_id: str) -> None:
        """Move the link of a renamed entity to its new entity id."""
        if (identifiers := self._links.pop(old_entity_id, None)) is None:
            return
        self._links[entity_id] = identifiers
        if failures := self._failures.pop(old_entity_id, 0):
            self._failures[entity_id] = failures
        self._async_save()
        self._async_reapply(entity_id)

    @callback
    def _async_reapply(self, entity_id: str) -> None:
        """Re-link an entity the registry left without a device."""
        if (identifiers := self._links.get(entity_id)) is None:
            return

        entity_registry = er.async_get(self.hass)
        if (entry := entity_registry.async_get(entity_id)) is None:
            return
        if entry.device_id is not None:
            # The owning integration linked the entity itself; leave its choice alone.
            return

        try:
            device = async_resolve_device(self.hass, identifiers)
            async_set_device_link(entity_registry, entity_id, device.id)
        except HomeAssistantError as err:
            self._async_log_failure(entity_id, identifiers, err)
            return

        self._failures.pop(entity_id, None)
        LOGGER.debug("Re-linked %s to device %s", entity_id, device.id)

    @callback
    def _async_log_failure(
        self, entity_id: str, identifiers: Identifiers, err: HomeAssistantError
    ) -> None:
        failures = self._failures[entity_id] = self._failures.get(entity_id, 0) + 1
        log = LOGGER.debug if failures > REAPPLY_FAILURE_LOG_LIMIT else LOGGER.warning
        log(
            "Could not re-link %s to the device with identifiers %s: %s",
            entity_id,
            format_identifiers(identifiers),
            err,
        )


@callback
def async_get_reapplier(hass: HomeAssistant, domain: str) -> DeviceLinkReapplier | None:
    """Return the reapplier of the loaded config entry, if there is one."""
    if not (entries := hass.config_entries.async_loaded_entries(domain)):
        return None
    return entries[0].runtime_data
