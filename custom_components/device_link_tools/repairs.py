"""Repairs platform for the Device link tools integration."""

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import DeviceSelector

from .helpers import async_resolve_device_id, async_set_device_link
from .reapply import (
    DeviceLinkToolsConfigEntry,
    async_options_with_links,
    async_stored_links,
)


class UnresolvedLinkRepairFlow(RepairsFlow):
    """Ask for a device again when a recorded link can no longer be resolved."""

    def __init__(self, entry: DeviceLinkToolsConfigEntry, entity_id: str) -> None:
        """Initialize the flow."""
        self._entry_id = entry.entry_id
        self._entity_id = entity_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the first step of the fix flow."""
        # The flow manager passes {"issue_id": ...} as user_input to this step;
        # delegate so the form step can tell rendering from an (empty) submission
        return await self.async_step_select_device()

    async def async_step_select_device(
        self, user_input: dict[str, str] | None = None
    ) -> RepairsFlowResult:
        """Handle the device selection step."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None:
            return self.async_abort(reason="entry_removed")

        errors: dict[str, str] = {}
        if user_input is not None:
            links = async_stored_links(entry)
            device_id = user_input.get(ATTR_DEVICE_ID)
            try:
                if device_id:
                    device = async_resolve_device_id(self.hass, device_id)
                    links[self._entity_id] = device.identifiers
                else:
                    links.pop(self._entity_id, None)
                    device = None
            except HomeAssistantError:
                errors[ATTR_DEVICE_ID] = "invalid_device"
            else:
                async_set_device_link(
                    er.async_get(self.hass),
                    self._entity_id,
                    device.id if device else None,
                )
                self.hass.config_entries.async_update_entry(
                    entry, options=async_options_with_links(entry, links)
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="select_device",
            data_schema=vol.Schema({vol.Optional(ATTR_DEVICE_ID): DeviceSelector()}),
            description_placeholders={"entity_id": self._entity_id},
            errors=errors,
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create a fix flow."""
    if (
        issue_id.startswith("unresolved_link_")
        and data is not None
        and (entry := hass.config_entries.async_get_entry(str(data["entry_id"])))
        is not None
    ):
        return UnresolvedLinkRepairFlow(entry, str(data["entity_id"]))
    raise ValueError(f"Unknown issue {issue_id}")
