"""Config and options flow for the Device link tools integration."""

from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    DeviceSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN
from .helpers import async_resolve_device_id
from .reapply import DeviceLinkToolsConfigEntry, async_apply_link, async_stored_links

# Failures the add form can report on the field itself; anything else is reported as a
# generic invalid device.
_FORM_ERRORS = {
    "device_id_composite",
    "device_id_unknown",
    "device_without_identifiers",
    "entity_not_registered",
    "link_set_elsewhere",
}


@callback
def _form_error(err: HomeAssistantError) -> str:
    """Return the form error key for a failure raised while linking."""
    key = err.translation_key or ""
    return key if key in _FORM_ERRORS else "invalid_device"


class DeviceLinkToolsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Confirmation-only flow: there is nothing to configure."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: DeviceLinkToolsConfigEntry,
    ) -> OptionsFlowWithReload:
        """Get the options flow for this handler."""
        return DeviceLinkToolsOptionsFlow()

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            return self.async_create_entry(title="Device link tools", data={})

        return self.async_show_form(step_id="user")


class DeviceLinkToolsOptionsFlow(OptionsFlowWithReload):
    """Manage the recorded links from the UI."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to add or remove a link."""
        return self.async_show_menu(
            step_id="init", menu_options=["add_link", "remove_link"]
        )

    async def async_step_add_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Link entities to a picked device."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                device = async_resolve_device_id(self.hass, user_input[ATTR_DEVICE_ID])
                async_apply_link(self.hass, user_input[ATTR_ENTITY_ID], device)
            except HomeAssistantError as err:
                errors["base"] = _form_error(err)
            else:
                # async_apply_link already wrote the options; handing them back
                # unchanged just ends the flow.
                return self.async_create_entry(data=dict(self.config_entry.options))

        return self.async_show_form(
            step_id="add_link",
            data_schema=vol.Schema(
                {
                    vol.Required(ATTR_ENTITY_ID): EntitySelector(
                        EntitySelectorConfig(multiple=True)
                    ),
                    vol.Required(ATTR_DEVICE_ID): DeviceSelector(),
                }
            ),
            errors=errors,
        )

    async def async_step_remove_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Unlink entities from the device they were linked to."""
        links = async_stored_links(self.config_entry)
        if not links:
            return self.async_abort(reason="no_links")

        if user_input is not None:
            async_apply_link(self.hass, user_input[ATTR_ENTITY_ID], None)
            return self.async_create_entry(data=dict(self.config_entry.options))

        return self.async_show_form(
            step_id="remove_link",
            data_schema=vol.Schema(
                {
                    vol.Required(ATTR_ENTITY_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=sorted(links),
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
