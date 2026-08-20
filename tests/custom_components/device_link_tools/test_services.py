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

from tests.common import MockUser

SOLAR_POWER = "sensor.solar_power"
GRID_IMPORT = "sensor.grid_import"

pytestmark = pytest.mark.usefixtures("config_entry")


@pytest.mark.parametrize(
    ("linked_device", "identifiers", "connections", "name"),
    [
        pytest.param("no_device_id", [], [], None, id="unlinked"),
        pytest.param(
            "device_id",
            [["mqtt", "8848_5"]],
            [["mac", "aa:bb:cc:dd:ee:ff"]],
            "Boiler",
            id="linked",
        ),
    ],
)
@pytest.mark.usefixtures("entity_entry", "device")
async def test_read_identifiers(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    request: pytest.FixtureRequest,
    linked_device: str,
    identifiers: list[list[str]],
    connections: list[list[str]],
    name: str | None,
) -> None:
    """Test reading the device link of an entity."""
    device_id = request.getfixturevalue(linked_device)
    entity_registry.async_update_entity(SOLAR_POWER, device_id=device_id)

    response = await hass.services.async_call(
        DOMAIN,
        "read_identifiers",
        {"entity_id": SOLAR_POWER},
        blocking=True,
        return_response=True,
    )

    assert response == {
        "entity_id": SOLAR_POWER,
        "device_id": device_id,
        "identifiers": identifiers,
        "connections": connections,
        "name": name,
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


@pytest.mark.parametrize(
    ("service", "data", "extra_fixtures", "translation_key"),
    [
        pytest.param(
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:nope"},
            (),
            "device_not_found",
            id="no_device_carries_the_identifiers",
        ),
        pytest.param(
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
            ("colliding_device",),
            "identifiers_ambiguous",
            id="two_devices_carry_the_identifiers",
        ),
        pytest.param(
            "add_identifier",
            {"entity_id": "sensor.not_registered", "identifiers": "mqtt:8848_5"},
            (),
            "entity_not_registered",
            id="entity_has_no_registry_entry",
        ),
        pytest.param(
            "remove_identifier",
            {"entity_id": "sensor.not_registered"},
            (),
            "entity_not_registered",
            id="unlinking_an_entity_without_registry_entry",
        ),
        pytest.param(
            "clone",
            {"source_entity_id": SOLAR_POWER, "target_entity_id": GRID_IMPORT},
            (),
            "source_not_linked",
            id="clone_source_has_no_device",
        ),
    ],
)
@pytest.mark.usefixtures("entity_entry", "second_entity_entry", "device")
async def test_service_validation_error(
    hass: HomeAssistant,
    request: pytest.FixtureRequest,
    service: str,
    data: dict[str, Any],
    extra_fixtures: tuple[str, ...],
    translation_key: str,
) -> None:
    """Test the input errors reported to the user."""
    for fixture in extra_fixtures:
        request.getfixturevalue(fixture)

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)

    assert err.value.translation_key == translation_key


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


@pytest.mark.parametrize(
    ("service", "data"),
    [
        pytest.param(
            "add_identifier",
            {"entity_id": SOLAR_POWER, "identifiers": "mqtt:8848_5"},
            id="add_identifier",
        ),
        pytest.param(
            "remove_identifier", {"entity_id": SOLAR_POWER}, id="remove_identifier"
        ),
        pytest.param(
            "clone",
            {"source_entity_id": SOLAR_POWER, "target_entity_id": GRID_IMPORT},
            id="clone",
        ),
    ],
)
@pytest.mark.usefixtures("entity_entry", "second_entity_entry", "device")
async def test_mutations_require_admin(
    hass: HomeAssistant,
    hass_read_only_user: MockUser,
    service: str,
    data: dict[str, Any],
) -> None:
    """Test a non-admin user cannot rewrite the registry."""
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN,
            service,
            data,
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
