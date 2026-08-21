"""Actions to link entities to a device by hand."""

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_NAME
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.service import async_register_admin_service

from .const import (
    ATTR_CONNECTIONS,
    ATTR_IDENTIFIERS,
    ATTR_SOURCE_ENTITY_ID,
    ATTR_TARGET_ENTITY_ID,
    ATTR_UNCHANGED,
    ATTR_UPDATED,
    DOMAIN,
    SERVICE_ADD_IDENTIFIER,
    SERVICE_CLONE,
    SERVICE_READ_IDENTIFIERS,
    SERVICE_REMOVE_IDENTIFIER,
)
from .helpers import (
    Identifiers,
    as_pairs,
    async_device_identifiers,
    async_resolve_device,
    async_resolve_device_id,
    async_resolve_entry,
    async_set_device_link,
    parse_identifiers,
)
from .reapply import async_get_reapplier

ENTITY_IDS = vol.All(cv.ensure_list, cv.entity_ids_or_uuids)

READ_IDENTIFIERS_SCHEMA = vol.Schema(
    {vol.Required(ATTR_ENTITY_ID): cv.entity_id_or_uuid}
)

ADD_IDENTIFIER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ENTITY_ID): ENTITY_IDS,
        vol.Exclusive(ATTR_IDENTIFIERS, "device"): parse_identifiers,
        vol.Exclusive(ATTR_DEVICE_ID, "device"): cv.string,
    }
)

REMOVE_IDENTIFIER_SCHEMA = vol.Schema({vol.Required(ATTR_ENTITY_ID): ENTITY_IDS})

CLONE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SOURCE_ENTITY_ID): cv.entity_id_or_uuid,
        vol.Required(ATTR_TARGET_ENTITY_ID): ENTITY_IDS,
    }
)


async def async_read_identifiers(call: ServiceCall) -> ServiceResponse:
    """Read the identifiers of the device an entity is linked to."""
    entity_registry = er.async_get(call.hass)
    entry = async_resolve_entry(entity_registry, call.data[ATTR_ENTITY_ID])

    if entry.device_id is None:
        return {
            ATTR_ENTITY_ID: entry.entity_id,
            ATTR_DEVICE_ID: None,
            ATTR_IDENTIFIERS: [],
            ATTR_CONNECTIONS: [],
            ATTR_NAME: None,
        }

    identifiers, connections, name = async_device_identifiers(
        call.hass, entry.device_id
    )
    return {
        ATTR_ENTITY_ID: entry.entity_id,
        ATTR_DEVICE_ID: entry.device_id,
        ATTR_IDENTIFIERS: as_pairs(identifiers),
        ATTR_CONNECTIONS: as_pairs(connections),
        ATTR_NAME: name,
    }


async def async_add_identifier(call: ServiceCall) -> ServiceResponse:
    """Link entities to a device given by its identifiers or by its id."""
    if (device_id := call.data.get(ATTR_DEVICE_ID)) is not None:
        device = async_resolve_device_id(call.hass, device_id)
    elif (identifiers := call.data.get(ATTR_IDENTIFIERS)) is not None:
        device = async_resolve_device(call.hass, identifiers)
    else:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="device_target_required"
        )

    return _async_link(
        call.hass, call.data[ATTR_ENTITY_ID], device.id, device.identifiers
    )


async def async_remove_identifier(call: ServiceCall) -> ServiceResponse:
    """Unlink entities from the device they are linked to."""
    return _async_link(call.hass, call.data[ATTR_ENTITY_ID], None, None)


async def async_clone(call: ServiceCall) -> ServiceResponse:
    """Copy the device link of a source entity onto target entities."""
    entity_registry = er.async_get(call.hass)
    source = async_resolve_entry(entity_registry, call.data[ATTR_SOURCE_ENTITY_ID])

    if source.device_id is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="source_not_linked",
            translation_placeholders={"entity_id": source.entity_id},
        )

    identifiers, _, _ = async_device_identifiers(call.hass, source.device_id)
    return _async_link(
        call.hass, call.data[ATTR_TARGET_ENTITY_ID], source.device_id, identifiers
    )


@callback
def _async_link(
    hass: HomeAssistant,
    entity_ids: list[str],
    device_id: str | None,
    identifiers: Identifiers | None,
) -> ServiceResponse:
    """Apply a device link to every entity and record it for re-application."""
    entity_registry = er.async_get(hass)
    resolved = [
        async_resolve_entry(entity_registry, entity_id).entity_id
        for entity_id in entity_ids
    ]

    updated: list[str] = []
    unchanged: list[str] = []
    for entity_id in resolved:
        changed = async_set_device_link(entity_registry, entity_id, device_id)
        (updated if changed else unchanged).append(entity_id)

    if (reapplier := async_get_reapplier(hass, DOMAIN)) is not None:
        if identifiers is None:
            reapplier.async_forget(resolved)
        else:
            reapplier.async_track(resolved, identifiers)

    return {
        ATTR_DEVICE_ID: device_id,
        ATTR_IDENTIFIERS: as_pairs(identifiers) if identifiers else [],
        ATTR_UPDATED: updated,
        ATTR_UNCHANGED: unchanged,
    }


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the device link tools actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_IDENTIFIERS,
        async_read_identifiers,
        schema=READ_IDENTIFIERS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    for service_name, handler, schema in (
        (SERVICE_ADD_IDENTIFIER, async_add_identifier, ADD_IDENTIFIER_SCHEMA),
        (SERVICE_REMOVE_IDENTIFIER, async_remove_identifier, REMOVE_IDENTIFIER_SCHEMA),
        (SERVICE_CLONE, async_clone, CLONE_SCHEMA),
    ):
        async_register_admin_service(
            hass,
            DOMAIN,
            service_name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
