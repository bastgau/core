"""Test managing the recorded links from the options flow."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import MockConfigEntry

SOLAR_POWER = "sensor.solar_power"
GRID_IMPORT = "sensor.grid_import"
LINKS = "links"

pytestmark = pytest.mark.usefixtures("config_entry")


async def _async_menu(hass: HomeAssistant, config_entry: MockConfigEntry) -> str:
    """Open the options flow and return its flow id."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {"add_link", "remove_link"}
    return result["flow_id"]


@pytest.mark.usefixtures("entity_entry", "second_entity_entry")
async def test_add_link(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test linking several entities to a picked device."""
    flow_id = await _async_menu(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "add_link"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "add_link"

    result = await hass.config_entries.options.async_configure(
        flow_id,
        {"entity_id": [SOLAR_POWER, GRID_IMPORT], "device_id": device.id},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id
    assert entity_registry.async_get(GRID_IMPORT).device_id == device.id
    assert config_entry.options[LINKS] == {
        GRID_IMPORT: [["mqtt", "8848_5"]],
        SOLAR_POWER: [["mqtt", "8848_5"]],
    }


@pytest.mark.usefixtures("device")
async def test_add_link_unregistered_entity(
    hass: HomeAssistant, config_entry: MockConfigEntry, device: dr.DeviceEntry
) -> None:
    """Test the form reports an entity that has no registry entry."""
    flow_id = await _async_menu(hass, config_entry)
    await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "add_link"}
    )

    result = await hass.config_entries.options.async_configure(
        flow_id, {"entity_id": ["sensor.not_registered"], "device_id": device.id}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_not_registered"}


@pytest.mark.usefixtures("entity_entry")
async def test_add_link_unknown_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test the form reports a device that no longer exists."""
    flow_id = await _async_menu(hass, config_entry)
    await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "add_link"}
    )

    result = await hass.config_entries.options.async_configure(
        flow_id, {"entity_id": [SOLAR_POWER], "device_id": "does-not-exist"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "device_id_unknown"}


@pytest.mark.usefixtures("entity_entry")
async def test_remove_link(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test unlinking an entity from the options flow."""
    await hass.services.async_call(
        "device_link_tools",
        "add_identifier",
        {"entity_id": SOLAR_POWER, "device_id": device.id},
        blocking=True,
    )

    flow_id = await _async_menu(hass, config_entry)
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "remove_link"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "remove_link"

    result = await hass.config_entries.options.async_configure(
        flow_id, {"entity_id": [SOLAR_POWER]}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entity_registry.async_get(SOLAR_POWER).device_id is None
    assert config_entry.options[LINKS] == {}


async def test_remove_link_without_links(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test the remove step aborts when nothing is linked."""
    flow_id = await _async_menu(hass, config_entry)

    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "remove_link"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_links"


@pytest.mark.usefixtures("entity_entry")
async def test_add_link_refuses_an_already_linked_entity(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
    other_device: dr.DeviceEntry,
) -> None:
    """Test the form reports an entity that is already on another device."""
    entity_registry.async_update_entity(SOLAR_POWER, device_id=device.id)
    flow_id = await _async_menu(hass, config_entry)
    await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "add_link"}
    )

    result = await hass.config_entries.options.async_configure(
        flow_id, {"entity_id": [SOLAR_POWER], "device_id": other_device.id}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "entity_already_linked"}
    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id
