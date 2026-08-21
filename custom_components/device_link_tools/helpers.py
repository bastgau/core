"""Helpers to read and rewrite the device link of an entity registry entry."""

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import ATTR_IDENTIFIER, DOMAIN

type Identifiers = set[tuple[str, str]]


def parse_identifier(value: Any) -> tuple[str, str]:
    """Coerce a single device identifier into a (domain, identifier) tuple."""
    if isinstance(value, str):
        domain, separator, identifier = value.partition(":")
        if not separator or not domain or not identifier:
            raise vol.Invalid(
                f"expected an identifier of the form 'domain:identifier', got {value!r}"
            )
        return (domain, identifier)

    if isinstance(value, Mapping):
        if CONF_DOMAIN in value or ATTR_IDENTIFIER in value:
            if (domain := value.get(CONF_DOMAIN)) is None or (
                identifier := value.get(ATTR_IDENTIFIER)
            ) is None:
                raise vol.Invalid(
                    "expected a mapping with the keys 'domain' and 'identifier', got "
                    f"{sorted(str(key) for key in value)}"
                )
            return (str(domain), str(identifier))
        if len(value) == 1:
            domain, identifier = next(iter(value.items()))
            return (str(domain), str(identifier))
        raise vol.Invalid(
            "expected a mapping of a single domain to a single identifier, got "
            f"{sorted(str(key) for key in value)}"
        )

    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise vol.Invalid(
                f"expected an identifier of exactly 2 items, got {len(value)}"
            )
        return (str(value[0]), str(value[1]))

    raise vol.Invalid(f"invalid device identifier: {value!r}")


def parse_identifiers(value: Any) -> Identifiers:
    """Validate the identifiers field into a set of (domain, identifier) tuples.

    A bare pair of colon-free strings - ["mqtt", "8848_5"] - is read as one identifier
    rather than as two malformed ones.
    """
    items: Any
    if isinstance(value, Mapping):
        if CONF_DOMAIN in value or ATTR_IDENTIFIER in value or len(value) <= 1:
            items = [value]
        else:
            items = [{domain: identifier} for domain, identifier in value.items()]
    elif isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple)):
        if len(value) == 2 and all(
            isinstance(item, str) and ":" not in item for item in value
        ):
            items = [value]
        else:
            items = value
    else:
        raise vol.Invalid(f"expected a list of device identifiers, got {value!r}")

    if not (identifiers := {parse_identifier(item) for item in items}):
        raise vol.Invalid("expected at least one device identifier")
    return identifiers


def format_identifiers(identifiers: Identifiers) -> str:
    """Format identifiers for an error message."""
    return ", ".join(sorted(f"{domain}:{value}" for domain, value in identifiers))


def as_pairs(values: set[tuple[str, str]]) -> list[list[str]]:
    """Convert registry tuples to the plain lists a service response allows."""
    return sorted([first, second] for first, second in values)


@callback
def async_resolve_entry(
    entity_registry: er.EntityRegistry, entity_id_or_uuid: str
) -> er.RegistryEntry:
    """Return the registry entry of an entity, or explain why there is none."""
    if (entry := entity_registry.async_get(entity_id_or_uuid)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entity_not_registered",
            translation_placeholders={"entity_id": entity_id_or_uuid},
        )
    return entry


@callback
def async_resolve_device(
    hass: HomeAssistant, identifiers: Identifiers
) -> dr.DeviceEntry:
    """Resolve identifiers to the single device they designate."""
    device_registry = dr.async_get(hass)

    # Deliberately not async_get_device: it collapses the splits of a pre-migration
    # composite device into a composite whose id async_update_entity then silently
    # refuses. async_get_devices only ever returns registered devices.
    matches = device_registry.async_get_devices(identifiers=identifiers)

    if not matches:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"identifiers": format_identifiers(identifiers)},
        )

    if len(matches) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="identifiers_ambiguous",
            translation_placeholders={
                "identifiers": format_identifiers(identifiers),
                "devices": ", ".join(
                    sorted(
                        f"{device.name_by_user or device.name} ({device.id})"
                        for device in matches
                    )
                ),
            },
        )

    return matches[0]


@callback
def async_resolve_device_id(hass: HomeAssistant, device_id: str) -> dr.DeviceEntry:
    """Resolve a device id to a device an entity can be linked to."""
    device_registry = dr.async_get(hass)

    # True for a pre-migration composite id, False for a registered device, None for an
    # unknown one. Check it first: async_get synthesizes a composite rather than
    # returning None, and the entity registry then declines the link.
    if device_registry.async_is_composite_device_id(device_id):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_id_composite",
            translation_placeholders={"device_id": device_id},
        )

    if (device := device_registry.async_get(device_id)) is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_id_unknown",
            translation_placeholders={"device_id": device_id},
        )

    if not device.identifiers:
        # The link is recorded by identifiers so it can be re-applied; a device that has
        # none could only be linked until the next restart.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_without_identifiers",
            translation_placeholders={
                "device_id": device_id,
                "name": device.name_by_user or device.name or device_id,
            },
        )

    return device


@callback
def async_device_identifiers(
    hass: HomeAssistant, device_id: str
) -> tuple[Identifiers, set[tuple[str, str]], str | None]:
    """Return the identifiers, connections and name behind a linked device id.

    An entity can hold the id of a pre-migration composite device. async_get synthesizes
    a read-only composite from the devices it was split into, so the identifiers and
    connections returned for such an id are the union of theirs.
    """
    if (device := dr.async_get(hass).async_get(device_id)) is None:
        return set(), set(), None
    return device.identifiers, device.connections, device.name_by_user or device.name


@callback
def async_set_device_link(
    entity_registry: er.EntityRegistry, entity_id: str, device_id: str | None
) -> bool:
    """Set or clear the device link of a registry entry, returning whether it changed."""
    entry = async_resolve_entry(entity_registry, entity_id)
    if entry.device_id == device_id:
        return False

    try:
        updated = entity_registry.async_update_entity(
            entry.entity_id, device_id=device_id
        )
    except ValueError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="update_failed",
            translation_placeholders={
                "entity_id": entry.entity_id,
                "error": str(err),
            },
        ) from err

    if updated.device_id != device_id:
        # The entity registry declines composite device ids by dropping the update
        # instead of raising, which would otherwise be reported as a success.
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="link_refused",
            translation_placeholders={
                "entity_id": entry.entity_id,
                "device_id": device_id or "",
            },
        )

    return True
