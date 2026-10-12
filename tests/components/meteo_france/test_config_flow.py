"""Tests for the Meteo-France config flow."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

from meteofrance_api.model import Place
import pytest

from homeassistant.components.meteo_france.const import (
    CONF_CITY,
    CONF_LOCATION_ENTITY,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    CONF_LATITUDE,
    CONF_LONGITUDE,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry

CITY_1_POSTAL = "74220"
CITY_1_NAME = "La Clusaz"
CITY_1_LAT = 45.90417
CITY_1_LON = 6.42306
CITY_1_COUNTRY = "FR"
CITY_1_ADMIN = "Rhône-Alpes"
CITY_1_ADMIN2 = "74"
CITY_1 = Place(
    {
        "name": CITY_1_NAME,
        "lat": CITY_1_LAT,
        "lon": CITY_1_LON,
        "country": CITY_1_COUNTRY,
        "admin": CITY_1_ADMIN,
        "admin2": CITY_1_ADMIN2,
    }
)

CITY_2_NAME = "Auch"
CITY_2_LAT = 43.64528
CITY_2_LON = 0.58861
CITY_2_COUNTRY = "FR"
CITY_2_ADMIN = "Midi-Pyrénées"
CITY_2_ADMIN2 = "32"
CITY_2 = Place(
    {
        "name": CITY_2_NAME,
        "lat": CITY_2_LAT,
        "lon": CITY_2_LON,
        "country": CITY_2_COUNTRY,
        "admin": CITY_2_ADMIN,
        "admin2": CITY_2_ADMIN2,
    }
)

CITY_3_NAME = "Auchel"
CITY_3_LAT = 50.50833
CITY_3_LON = 2.47361
CITY_3_COUNTRY = "FR"
CITY_3_ADMIN = "Nord-Pas-de-Calais"
CITY_3_ADMIN2 = "62"
CITY_3 = Place(
    {
        "name": CITY_3_NAME,
        "lat": CITY_3_LAT,
        "lon": CITY_3_LON,
        "country": CITY_3_COUNTRY,
        "admin": CITY_3_ADMIN,
        "admin2": CITY_3_ADMIN2,
    }
)


@pytest.fixture(name="client")
def mock_controller_client() -> Generator[MagicMock]:
    """Mock a successful client."""
    with patch(
        "homeassistant.components.meteo_france.config_flow.MeteoFranceClient",
        update=False,
    ) as service_mock:
        service_mock.return_value.search_places.return_value = [CITY_1]
        yield service_mock


@pytest.fixture(autouse=True)
def mock_setup() -> Generator[None]:
    """Prevent setup."""
    with patch(
        "homeassistant.components.meteo_france.async_setup_entry",
        return_value=True,
    ):
        yield


async def _async_start_city_flow(hass: HomeAssistant) -> dict:
    """Start a user flow and pick the fixed location menu option."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "city"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "city"
    assert result["errors"] == {}
    return result


@pytest.mark.usefixtures("client")
async def test_user(hass: HomeAssistant) -> None:
    """Test user config."""
    result = await _async_start_city_flow(hass)

    # test with all provided with search returning only 1 place
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: CITY_1_POSTAL},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"{CITY_1_LAT}, {CITY_1_LON}"
    assert result["title"] == f"{CITY_1}"
    assert result["data"][CONF_LATITUDE] == str(CITY_1_LAT)
    assert result["data"][CONF_LONGITUDE] == str(CITY_1_LON)


async def test_user_list(hass: HomeAssistant, client: MagicMock) -> None:
    """Test user config."""

    client.return_value.search_places.return_value = [CITY_2, CITY_3]

    result = await _async_start_city_flow(hass)

    # test with all provided with search returning more than 1 place
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: CITY_2_NAME},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "cities"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: f"{CITY_3};{CITY_3_LAT};{CITY_3_LON}"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"{CITY_3_LAT}, {CITY_3_LON}"
    assert result["title"] == f"{CITY_3}"
    assert result["data"][CONF_LATITUDE] == str(CITY_3_LAT)
    assert result["data"][CONF_LONGITUDE] == str(CITY_3_LON)


async def test_search_failed(hass: HomeAssistant, client: MagicMock) -> None:
    """Test error displayed if no result in search."""
    client.return_value.search_places.return_value = []

    result = await _async_start_city_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: CITY_1_POSTAL},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_CITY: "empty"}

    # recover
    client.return_value.search_places.return_value = [CITY_1]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: CITY_1_POSTAL},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == f"{CITY_1_LAT}, {CITY_1_LON}"
    assert result["title"] == f"{CITY_1}"
    assert result["data"][CONF_LATITUDE] == str(CITY_1_LAT)
    assert result["data"][CONF_LONGITUDE] == str(CITY_1_LON)


@pytest.mark.usefixtures("client")
async def test_abort_if_already_setup(hass: HomeAssistant) -> None:
    """Test we abort if already setup."""
    MockConfigEntry(
        domain=DOMAIN,
        data={CONF_LATITUDE: CITY_1_LAT, CONF_LONGITUDE: CITY_1_LON},
        unique_id=f"{CITY_1_LAT}, {CITY_1_LON}",
    ).add_to_hass(hass)
    result = await _async_start_city_flow(hass)

    # Should fail, same CITY same postal code (flow)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CITY: CITY_1_POSTAL},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def _async_start_entity_flow(hass: HomeAssistant) -> dict:
    """Start a user flow and pick the entity tracking menu option."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "entity"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "entity"
    return result


async def test_entity(hass: HomeAssistant, tracker: er.RegistryEntry) -> None:
    """Test following a device tracker."""
    result = await _async_start_entity_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCATION_ENTITY: tracker.entity_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == tracker.id
    assert result["title"] == "phone"
    assert result["data"] == {CONF_LOCATION_ENTITY: tracker.id}


@pytest.mark.parametrize(
    ("entity_id", "error"),
    [
        pytest.param(
            "device_tracker.unregistered", "entity_not_found", id="not_registered"
        ),
        pytest.param("device_tracker.disabled", "entity_disabled", id="disabled"),
        pytest.param(
            "device_tracker.no_coordinates",
            "entity_no_coordinates",
            id="no_coordinates",
        ),
    ],
)
async def test_entity_errors(
    hass: HomeAssistant,
    entity_registry: er.EntityRegistry,
    tracker: er.RegistryEntry,
    entity_id: str,
    error: str,
) -> None:
    """Test invalid entities are rejected and the flow can recover."""
    location = {ATTR_LATITUDE: CITY_1_LAT, ATTR_LONGITUDE: CITY_1_LON}
    hass.states.async_set("device_tracker.unregistered", "not_home", location)
    entity_registry.async_get_or_create(
        "device_tracker",
        "test",
        "disabled",
        suggested_object_id="disabled",
        disabled_by=er.RegistryEntryDisabler.USER,
    )
    entity_registry.async_get_or_create(
        "device_tracker", "test", "no_coordinates", suggested_object_id="no_coordinates"
    )
    hass.states.async_set("device_tracker.no_coordinates", "home")

    result = await _async_start_entity_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCATION_ENTITY: entity_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCATION_ENTITY: tracker.entity_id}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_entity_already_configured(
    hass: HomeAssistant, tracker: er.RegistryEntry
) -> None:
    """Test we abort if the entity is already followed."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_LOCATION_ENTITY: tracker.id}, unique_id=tracker.id
    ).add_to_hass(hass)

    result = await _async_start_entity_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOCATION_ENTITY: tracker.entity_id}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
