"""The Device link tools integration."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .reapply import DeviceLinkReapplier, DeviceLinkToolsConfigEntry
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the device link tools actions."""
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: DeviceLinkToolsConfigEntry
) -> bool:
    """Set up device link tools from a config entry."""
    reapplier = DeviceLinkReapplier(hass, entry)
    entry.runtime_data = reapplier
    reapplier.async_setup()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DeviceLinkToolsConfigEntry
) -> bool:
    """Unload a config entry."""
    return True
