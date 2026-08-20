"""Test the Device link tools actions."""

from typing import Any

import pytest
import voluptuous as vol

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import (
    HomeAssistantError,
    ServiceValidationError,
    Unauthorized,
)
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.typing import UNDEFINED

from .conftest import DOMAIN

from tests.common import MockConfigEntry, MockUser

SOLAR_POWER = "sensor.solar_power"
GRID_IMPORT = "sensor.grid_import"

pytestmark = pytest.mark.usefixtures("config_entry")


@pytest.mark.usefixtures("entity_entry")
async def test_read_identifiers_unlinked(hass: HomeAssistant) -> None:
    """Test reading an entity that is not linked to any device."""
    response = await hass.services.async_call(
        DOMAIN,
        "read_identifiers",
        {"entity_id": SOLAR_POWER},
        blocking=True,
        return_response=True,
    )

    assert response == {
        "entity_id": SOLAR_POWER,
        "device_id": None,
        "identifiers": [],
        "connections": [],
        "name": None,
    }


@pytest.mark.usefixtures("entity_entry")
async def test_read_identifiers_linked(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test reading the identifiers of the linked device."""
    entity_registry.async_update_entity(SOLAR_POWER, device_id=device.id)

    response = await hass.services.async_call(
        DOMAIN,
        "read_identifiers",
        {"entity_id": SOLAR_POWER},
        blocking=True,
        return_response=True,
    )

    assert response == {
        "entity_id": SOLAR_POWER,
        "device_id": device.id,
        "identifiers": [["mqtt", "8848_5"]],
        "connections": [["mac", "aa:bb:cc:dd:ee:ff"]],
        "name": "Boiler",
    }


@pytest.mark.parametrize(
    "identifiers",
    [
        pytest.param("mqtt:8848_5", id="colon_string"),
        pytest.param(["mqtt:8848_5"], id="colon_string_list"),
        pytest.param(["mqtt", "8848_5"], id="bare_pair"),
        pytest.param([["mqtt", "8848_5"]], id="pair_list"),
        pytest.param({"mqtt": "8848_5"}, id="mapping"),
        pytest.param([{"mqtt": "8848_5"}], id="mapping_list"),
        pytest.param(
            [{"domain": "mqtt", "identifier": "8848_5"}], id="selector_mapping"
        ),
    ],
)
@pytest.mark.usefixtures("entity_entry")
async def test_add_identifier_accepted_formats(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
    identifiers: Any,
) -> None:
    """Test every accepted spelling of the identifiers field."""
    await hass.services.async_call(
        DOMAIN,
        "add_identifier",
        {"entity_id": SOLAR_POWER, "identifiers": identifiers},
        blocking=True,
    )

    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id


@pytest.mark.usefixtures("entity_entry", "second_entity_entry")
async def test_add_identifier_multiple_entities(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test linking several entities at once and the reported outcome."""
    response = await hass.services.async_call(
        DOMAIN,
        "add_identifier",
        {"entity_id": [SOLAR_POWER, GRID_IMPORT], "identifiers": "mqtt:8848_5"},
        blocking=True,
        return_response=True,
    )

    assert entity_registry.async_get(SOLAR_POWER).device_id == device.id
    assert entity_registry.async_get(GRID_IMPORT).device_id == device.id
    assert response == {
        "device_id": device.id,
        "identifiers": [["mqtt", "8848_5"]],
        "updated": [SOLAR_POWER, GRID_IMPORT],
        "unchanged": [],
    }


@pytest.mark.usefixtures("entity_entry")
async def test_add_identifier_reports_unchanged(
    hass: HomeAssistant, device: dr.DeviceEntry
) -> None:
    """Test an entity already linked to the device is reported as unchanged."""
    data = {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"}
    await hass.services.async_call(DOMAIN, "add_identifier", data, blocking=True)

    response = await hass.services.async_call(
        DOMAIN, "add_identifier", data, blocking=True, return_response=True
    )

    assert response["updated"] == []
    assert response["unchanged"] == [SOLAR_POWER]


@pytest.mark.usefixtures("entity_entry")
async def test_add_identifier_unknown_device(hass: HomeAssistant) -> None:
    """Test linking to identifiers no device carries."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:nope"},
            blocking=True,
        )

    assert err.value.translation_key == "device_not_found"


@pytest.mark.usefixtures("entity_entry", "device")
async def test_add_identifier_ambiguous(
    hass: HomeAssistant,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test identifiers shared by two devices are refused."""
    other_owner = MockConfigEntry(domain="tasmota", title="Tasmota")
    other_owner.add_to_hass(hass)
    device_registry.async_get_or_create(
        config_entry_id=other_owner.entry_id,
        identifiers={("mqtt", "8848_5")},
        name="Boiler bis",
    )

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
            blocking=True,
        )

    assert err.value.translation_key == "identifiers_ambiguous"


@pytest.mark.usefixtures("device")
async def test_add_identifier_unregistered_entity(hass: HomeAssistant) -> None:
    """Test an entity without a registry entry cannot be linked."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": "sensor.not_registered", "identifiers": "mqtt:8848_5"},
            blocking=True,
        )

    assert err.value.translation_key == "entity_not_registered"


@pytest.mark.parametrize(
    "identifiers",
    [
        pytest.param([], id="empty"),
        pytest.param("mqtt", id="missing_separator"),
        pytest.param(":8848_5", id="missing_domain"),
        pytest.param([["mqtt", "8848_5", "extra"]], id="too_many_items"),
        pytest.param([{"domain": "mqtt"}], id="incomplete_mapping"),
        pytest.param([12], id="not_an_identifier"),
    ],
)
@pytest.mark.usefixtures("entity_entry")
async def test_add_identifier_invalid_input(
    hass: HomeAssistant, identifiers: Any
) -> None:
    """Test malformed identifiers are rejected by the schema."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": identifiers},
            blocking=True,
        )


@pytest.mark.usefixtures("entity_entry")
async def test_add_identifier_refused_link(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    device: dr.DeviceEntry,
) -> None:
    """Test a link the entity registry silently drops is reported as an error."""
    monkeypatch.setattr(
        er.EntityRegistry,
        "_ignore_composite_device_id",
        lambda self, platform, device_id: UNDEFINED,
    )

    with pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
            blocking=True,
        )

    assert err.value.translation_key == "link_refused"


@pytest.mark.usefixtures("entity_entry")
async def test_remove_identifier(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test unlinking an entity from its device."""
    entity_registry.async_update_entity(SOLAR_POWER, device_id=device.id)

    response = await hass.services.async_call(
        DOMAIN,
        "remove_identifier",
        {"entity_id": SOLAR_POWER},
        blocking=True,
        return_response=True,
    )

    assert entity_registry.async_get(SOLAR_POWER).device_id is None
    assert response == {
        "device_id": None,
        "identifiers": [],
        "updated": [SOLAR_POWER],
        "unchanged": [],
    }


@pytest.mark.usefixtures("entity_entry", "second_entity_entry")
async def test_clone(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    device: dr.DeviceEntry,
) -> None:
    """Test copying the device link of a source entity."""
    entity_registry.async_update_entity(SOLAR_POWER, device_id=device.id)

    response = await hass.services.async_call(
        DOMAIN,
        "clone",
        {"source_entity_id": SOLAR_POWER, "target_entity_id": GRID_IMPORT},
        blocking=True,
        return_response=True,
    )

    assert entity_registry.async_get(GRID_IMPORT).device_id == device.id
    assert response["device_id"] == device.id
    assert response["identifiers"] == [["mqtt", "8848_5"]]


@pytest.mark.usefixtures("entity_entry", "second_entity_entry")
async def test_clone_source_not_linked(hass: HomeAssistant) -> None:
    """Test cloning from an entity that has no device."""
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "clone",
            {"source_entity_id": SOLAR_POWER, "target_entity_id": GRID_IMPORT},
            blocking=True,
        )

    assert err.value.translation_key == "source_not_linked"


@pytest.mark.usefixtures("entity_entry", "device")
async def test_mutations_require_admin(
    hass: HomeAssistant, hass_read_only_user: MockUser
) -> None:
    """Test a non-admin user cannot rewrite the registry."""
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
            blocking=True,
            context=Context(user_id=hass_read_only_user.id),
        )


@pytest.mark.usefixtures("entity_entry")
async def test_read_allowed_for_non_admin(
    hass: HomeAssistant, hass_read_only_user: MockUser
) -> None:
    """Test reading is not restricted to administrators."""
    response = await hass.services.async_call(
        DOMAIN,
        "read_identifiers",
        {"entity_id": SOLAR_POWER},
        blocking=True,
        return_response=True,
        context=Context(user_id=hass_read_only_user.id),
    )

    assert response["device_id"] is None
