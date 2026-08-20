"""Test that manual device links survive the owning integration re-adding entities."""

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import DOMAIN

from tests.common import MockConfigEntry

SOLAR_POWER = "sensor.solar_power"
LINKS = "links"


async def _async_link(hass: HomeAssistant) -> None:
    """Link the solar power sensor to the boiler device."""
    await hass.services.async_call(
        DOMAIN,
        "add_identifier",
        {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
        blocking=True,
    )


@pytest.mark.usefixtures("config_entry", "entity_entry")
async def test_link_reapplied_after_reset(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test a link cleared by the owning integration is restored."""
    await _async_link(hass)

    entity_registry.async_update_entity(SOLAR_POWER, device_id=None)
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id


@pytest.mark.usefixtures("config_entry", "entity_entry", "device")
async def test_reapply_does_not_loop(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Test re-linking fires one registry update and settles."""
    await _async_link(hass)

    events: list[er.EventEntityRegistryUpdatedData] = []
    hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, lambda event: events.append(event.data)
    )

    entity_registry.async_update_entity(SOLAR_POWER, device_id=None)
    await hass.async_block_till_done()

    assert len(events) == 2


@pytest.mark.usefixtures("config_entry", "entity_entry", "device")
async def test_owning_integration_device_kept(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    other_device: dr.DeviceEntry,
) -> None:
    """Test a device set by the owning integration is not overridden."""
    await _async_link(hass)

    entity_registry.async_update_entity(SOLAR_POWER, device_id=other_device.id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id == other_device.id


@pytest.mark.usefixtures("entity_entry", "device")
async def test_link_persisted(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Test the link is recorded in the config entry options."""
    await _async_link(hass)

    assert config_entry.options[LINKS] == {SOLAR_POWER: [["mqtt", "8848_5"]]}


@pytest.mark.usefixtures("entity_entry")
async def test_removing_link_stops_reapplying(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test an unlinked entity is not linked again."""
    await _async_link(hass)
    await hass.services.async_call(
        DOMAIN, "remove_identifier", {"entity_id": SOLAR_POWER}, blocking=True
    )

    assert config_entry.options[LINKS] == {}

    entity_registry.async_update_entity(SOLAR_POWER, device_id=device.id)
    entity_registry.async_update_entity(SOLAR_POWER, device_id=None)
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id is None


@pytest.mark.usefixtures("enable_custom_integrations", "entity_entry")
async def test_link_reapplied_at_startup(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test a stored link is applied when the integration sets up."""
    entry = MockConfigEntry(
        domain=DOMAIN, options={LINKS: {SOLAR_POWER: [["mqtt", "8848_5"]]}}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_stored_link_of_gone_entity_purged(hass: HomeAssistant) -> None:
    """Test a link kept for an entity that no longer exists is dropped."""
    entry = MockConfigEntry(
        domain=DOMAIN, options={LINKS: {SOLAR_POWER: [["mqtt", "8848_5"]]}}
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.options[LINKS] == {}


@pytest.mark.usefixtures("config_entry", "entity_entry", "device")
async def test_link_forgotten_when_entity_removed(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test removing the entity drops its stored link."""
    await _async_link(hass)

    entity_registry.async_remove(SOLAR_POWER)
    await hass.async_block_till_done()

    assert config_entry.options[LINKS] == {}


@pytest.mark.usefixtures("entity_entry")
async def test_link_follows_renamed_entity(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test the stored link follows an entity that is renamed."""
    await _async_link(hass)

    entity_registry.async_update_entity(SOLAR_POWER, new_entity_id="sensor.renamed")
    await hass.async_block_till_done()

    assert config_entry.options[LINKS] == {"sensor.renamed": [["mqtt", "8848_5"]]}
    assert entity_registry.async_get("sensor.renamed").device_id == device.id


@pytest.mark.usefixtures("config_entry", "entity_entry")
async def test_missing_device_logs_warning(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test a link that can no longer be resolved warns instead of raising."""
    await _async_link(hass)

    device_registry.async_remove_device(device.id)
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id is None
    assert "Could not re-link sensor.solar_power" in caplog.text
