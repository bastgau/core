"""Test the repair flow offered when a recorded link cannot be applied."""

from http import HTTPStatus

from aiohttp.test_utils import TestClient
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.setup import async_setup_component

from .conftest import DOMAIN, LINKS, SOLAR_POWER, async_link

from tests.common import MockConfigEntry
from tests.typing import ClientSessionGenerator

ISSUE_ID = f"unresolved_link_{SOLAR_POWER}"

pytestmark = pytest.mark.usefixtures("config_entry")


@pytest.fixture
async def unresolved_link(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_entry: er.RegistryEntry,
    device: dr.DeviceEntry,
) -> None:
    """Link the sensor, then make its device unresolvable."""
    await async_link(hass, SOLAR_POWER, device)
    device_registry.async_remove_device(device.id)
    await hass.async_block_till_done()


async def _async_start_fix_flow(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> tuple[str, TestClient]:
    """Start the repair flow and return its flow id and a client to drive it."""
    assert await async_setup_component(hass, "repairs", {})
    client = await hass_client()

    response = await client.post(
        "/api/repairs/issues/fix", json={"handler": DOMAIN, "issue_id": ISSUE_ID}
    )
    assert response.status == HTTPStatus.OK
    data = await response.json()
    assert data["step_id"] == "select_device"
    return data["flow_id"], client


@pytest.mark.usefixtures("unresolved_link")
async def test_issue_raised(
    issue_registry: ir.IssueRegistry, entity_registry: er.EntityRegistry
) -> None:
    """Test an unresolvable link raises a fixable issue."""
    issue = issue_registry.async_get_issue(DOMAIN, ISSUE_ID)

    assert issue is not None
    assert issue.is_fixable
    assert entity_registry.async_get(SOLAR_POWER).device_id is None


@pytest.mark.usefixtures("unresolved_link")
async def test_fix_flow_selects_a_device(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    other_device: dr.DeviceEntry,
) -> None:
    """Test picking another device relinks the entity and records it."""
    flow_id, client = await _async_start_fix_flow(hass, hass_client)

    response = await client.post(
        f"/api/repairs/issues/fix/{flow_id}", json={"device_id": other_device.id}
    )
    assert response.status == HTTPStatus.OK
    assert (await response.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id == other_device.id
    assert config_entry.options[LINKS] == {SOLAR_POWER: [["mqtt", "9000_1"]]}


@pytest.mark.usefixtures("unresolved_link")
async def test_fix_flow_without_device_stops_tracking(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test submitting no device drops the recorded link."""
    flow_id, client = await _async_start_fix_flow(hass, hass_client)

    response = await client.post(f"/api/repairs/issues/fix/{flow_id}", json={})
    assert response.status == HTTPStatus.OK
    assert (await response.json())["type"] == "create_entry"
    await hass.async_block_till_done()

    assert entity_registry.async_get(SOLAR_POWER).device_id is None
    assert config_entry.options[LINKS] == {}


@pytest.mark.usefixtures("unresolved_link")
async def test_fix_flow_rejects_unknown_device(
    hass: HomeAssistant, hass_client: ClientSessionGenerator
) -> None:
    """Test a device that cannot hold the link is refused."""
    flow_id, client = await _async_start_fix_flow(hass, hass_client)

    response = await client.post(
        f"/api/repairs/issues/fix/{flow_id}", json={"device_id": "does-not-exist"}
    )

    assert response.status == HTTPStatus.OK
    data = await response.json()
    assert data["errors"] == {"device_id": "invalid_device"}


@pytest.mark.usefixtures("unresolved_link")
async def test_fix_flow_aborts_when_entry_removed(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    config_entry: MockConfigEntry,
) -> None:
    """Test the flow gives up when the integration is removed while it is open."""
    flow_id, client = await _async_start_fix_flow(hass, hass_client)

    assert await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    response = await client.post(f"/api/repairs/issues/fix/{flow_id}", json={})

    assert response.status == HTTPStatus.OK
    data = await response.json()
    assert data["type"] == "abort"
    assert data["reason"] == "entry_removed"
