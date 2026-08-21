"""Repairs platform for the Device link tools integration."""

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow, RepairsFlowResult
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import DeviceSelector

from .helpers import async_resolve_device_id
from .reapply import DeviceLinkToolsConfigEntry, async_apply_link


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
            device_id = user_input.get(ATTR_DEVICE_ID)
            try:
                device = (
                    async_resolve_device_id(self.hass, device_id) if device_id else None
                )
                async_apply_link(self.hass, [self._entity_id], device)
            except HomeAssistantError:
                errors[ATTR_DEVICE_ID] = "invalid_device"
            else:
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
