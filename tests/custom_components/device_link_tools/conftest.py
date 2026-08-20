"""Fixtures for the Device link tools integration."""

from collections.abc import Generator
import importlib
import pathlib
import shutil
import sys

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import MockConfigEntry

DOMAIN = "device_link_tools"
SOURCE = pathlib.Path(__file__).parents[3] / "custom_components" / DOMAIN


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    """Provide a config directory holding the integration under test."""
    shutil.copytree(
        SOURCE, pathlib.Path(hass_tmp_config_dir) / "custom_components" / DOMAIN
    )
    return hass_tmp_config_dir


@pytest.fixture(autouse=True)
def reset_custom_components_import() -> Generator[None]:
    """Import custom_components from this test's config directory.

    Another test may have bound the name to a different directory earlier in the
    session, and the loader would then never see the copy made above.
    """
    _drop_custom_components()
    yield
    _drop_custom_components()


def _drop_custom_components() -> None:
    for name in [
        name
        for name in sys.modules
        if name == "custom_components" or name.startswith("custom_components.")
    ]:
        del sys.modules[name]
    importlib.invalidate_caches()


@pytest.fixture
async def config_entry(
    hass: HomeAssistant,
    enable_custom_integrations: None,
) -> MockConfigEntry:
    """Set up the integration and return its config entry."""
    entry = MockConfigEntry(domain=DOMAIN, title="Device link tools")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture
def owning_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return the config entry owning the devices used in the tests."""
    entry = MockConfigEntry(domain="mqtt", title="MQTT")
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def device(
    device_registry: dr.DeviceRegistry, owning_entry: MockConfigEntry
) -> dr.DeviceEntry:
    """Return a device an entity can be linked to."""
    return device_registry.async_get_or_create(
        config_entry_id=owning_entry.entry_id,
        identifiers={("mqtt", "8848_5")},
        connections={(dr.CONNECTION_NETWORK_MAC, "aa:bb:cc:dd:ee:ff")},
        name="Boiler",
    )


@pytest.fixture
def other_device(
    device_registry: dr.DeviceRegistry, owning_entry: MockConfigEntry
) -> dr.DeviceEntry:
    """Return a second, unrelated device."""
    return device_registry.async_get_or_create(
        config_entry_id=owning_entry.entry_id,
        identifiers={("mqtt", "9000_1")},
        name="Heat pump",
    )


@pytest.fixture
def entity_entry(entity_registry: er.EntityRegistry) -> er.RegistryEntry:
    """Return a registered entity that is not linked to any device."""
    return entity_registry.async_get_or_create(
        "sensor", "rest", "solar-power", suggested_object_id="solar_power"
    )


@pytest.fixture
def second_entity_entry(entity_registry: er.EntityRegistry) -> er.RegistryEntry:
    """Return a second registered entity that is not linked to any device."""
    return entity_registry.async_get_or_create(
        "sensor", "rest", "grid-import", suggested_object_id="grid_import"
    )
