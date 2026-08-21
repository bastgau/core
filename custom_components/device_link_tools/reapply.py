"""Keep manual device links alive across restarts and reloads.

An entity platform passes ``device_id=device.id if device else None`` on every add
(``homeassistant/helpers/entity_platform.py``), so the owning integration resets a
manually set device link whenever it re-adds the entity. The links recorded here are
re-applied at startup and whenever the registry clears one of them.
"""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.start import async_at_started

from .const import CONF_LINKS, DOMAIN, LOGGER
from .helpers import (
    Identifiers,
    as_pairs,
    async_resolve_device,
    async_resolve_entry,
    async_set_device_link,
    device_label,
    format_identifiers,
)

type DeviceLinkToolsConfigEntry = ConfigEntry[DeviceLinkReapplier]


@callback
def async_stored_links(entry: DeviceLinkToolsConfigEntry) -> dict[str, Identifiers]:
    """Return the links stored in the config entry options."""
    return {
        entity_id: {(pair[0], pair[1]) for pair in pairs}
        for entity_id, pairs in entry.options.get(CONF_LINKS, {}).items()
    }


@callback
def async_options_with_links(
    entry: DeviceLinkToolsConfigEntry, links: dict[str, Identifiers]
) -> dict[str, Any]:
    """Return the config entry options carrying the given links."""
    return {
        **entry.options,
        CONF_LINKS: {
            entity_id: as_pairs(identifiers)
            for entity_id, identifiers in sorted(links.items())
        },
    }


@callback
def async_tracked_entities(hass: HomeAssistant, domain: str) -> set[str]:
    """Return the entities whose device link this integration recorded."""
    if not (entries := hass.config_entries.async_loaded_entries(domain)):
        return set()
    return set(async_stored_links(entries[0]))


@callback
def _async_resolve_targets(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    entity_ids: list[str],
    device_id: str | None,
) -> list[str]:
    """Resolve the entities to link or unlink, refusing links set elsewhere.

    A link recorded here can be re-pointed or dropped. A link set elsewhere cannot be
    touched: one an entity's own integration declares is written back on every restart,
    so it has to be changed where it comes from. A device_id of None checks an unlink,
    which leaves only an entity that has no link at all untouched.
    """
    tracked = async_tracked_entities(hass, DOMAIN)
    entries = [
        async_resolve_entry(entity_registry, entity_id) for entity_id in entity_ids
    ]

    for entry in entries:
        if entry.device_id in (None, device_id) or entry.entity_id in tracked:
            continue
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="link_set_elsewhere",
            translation_placeholders={
                "entity_id": entry.entity_id,
                "name": device_label(
                    dr.async_get(hass).async_get(entry.device_id), entry.device_id
                ),
            },
        )

    return [entry.entity_id for entry in entries]


@callback
def async_apply_link(
    hass: HomeAssistant, entity_ids: list[str], device: dr.DeviceEntry | None
) -> tuple[list[str], list[str]]:
    """Link entities to a device, or unlink them, and record the outcome.

    The single write path: the actions, the options flow and the repair flow all go
    through it, so the refusals, the registry write and the recorded table stay in step.
    Returns the entities whose link changed, and those already in that state.
    """
    entity_registry = er.async_get(hass)
    device_id = device.id if device else None
    resolved = _async_resolve_targets(hass, entity_registry, entity_ids, device_id)

    updated: list[str] = []
    unchanged: list[str] = []
    for entity_id in resolved:
        changed = async_set_device_link(entity_registry, entity_id, device_id)
        (updated if changed else unchanged).append(entity_id)

    if (reapplier := async_get_reapplier(hass, DOMAIN)) is not None:
        if device is None:
            reapplier.async_forget(resolved)
        else:
            reapplier.async_track(resolved, device.identifiers)

    return updated, unchanged


@callback
def async_issue_id(entity_id: str) -> str:
    """Return the repair issue id reporting that a link cannot be applied."""
    return f"unresolved_link_{entity_id}"


class DeviceLinkReapplier:
    """Re-apply the device links the owning integrations reset."""

    def __init__(self, hass: HomeAssistant, entry: DeviceLinkToolsConfigEntry) -> None:
        """Initialize from the links stored in the config entry options."""
        self.hass = hass
        self.entry = entry
        self._links = async_stored_links(entry)

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
            ir.async_delete_issue(self.hass, DOMAIN, async_issue_id(entity_id))
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
            ir.async_delete_issue(self.hass, DOMAIN, async_issue_id(entity_id))
        self._async_save()

    @callback
    def _async_save(self) -> None:
        self.hass.config_entries.async_update_entry(
            self.entry, options=async_options_with_links(self.entry, self._links)
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
            self.hass.loop.call_soon(self.async_forget, [data["entity_id"]])
        elif (old_entity_id := data.get("old_entity_id")) is not None:
            self.hass.loop.call_soon(
                self._async_rename, old_entity_id, data["entity_id"]
            )
        else:
            self.hass.loop.call_soon(self._async_reapply, data["entity_id"])

    @callback
    def _async_rename(self, old_entity_id: str, entity_id: str) -> None:
        """Move the link of a renamed entity to its new entity id."""
        if (identifiers := self._links.pop(old_entity_id, None)) is None:
            return
        ir.async_delete_issue(self.hass, DOMAIN, async_issue_id(old_entity_id))
        self._links[entity_id] = identifiers
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
            self._async_report_unresolved(entity_id, identifiers, err)
            return

        ir.async_delete_issue(self.hass, DOMAIN, async_issue_id(entity_id))
        LOGGER.debug("Re-linked %s to device %s", entity_id, device.id)

    @callback
    def _async_report_unresolved(
        self, entity_id: str, identifiers: Identifiers, err: HomeAssistantError
    ) -> None:
        """Raise a repair issue asking the user to pick the device again."""
        LOGGER.debug(
            "Could not re-link %s to the device with identifiers %s: %s",
            entity_id,
            format_identifiers(identifiers),
            err,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            async_issue_id(entity_id),
            data={"entry_id": self.entry.entry_id, "entity_id": entity_id},
            is_fixable=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="unresolved_link",
            translation_placeholders={
                "entity_id": entity_id,
                "identifiers": format_identifiers(identifiers),
                "error": str(err),
            },
        )


@callback
def async_get_reapplier(hass: HomeAssistant, domain: str) -> DeviceLinkReapplier | None:
    """Return the reapplier of the loaded config entry, if there is one."""
    if not (entries := hass.config_entries.async_loaded_entries(domain)):
        return None
    return entries[0].runtime_data
