"""Constants for the Device link tools integration."""

import logging

DOMAIN = "device_link_tools"

LOGGER = logging.getLogger(__package__)

SERVICE_ADD_IDENTIFIER = "add_identifier"
SERVICE_CLONE = "clone"
SERVICE_READ_IDENTIFIERS = "read_identifiers"
SERVICE_REMOVE_IDENTIFIER = "remove_identifier"

ATTR_CONNECTIONS = "connections"
ATTR_IDENTIFIER = "identifier"
ATTR_IDENTIFIERS = "identifiers"
ATTR_SOURCE_ENTITY_ID = "source_entity_id"
ATTR_TARGET_ENTITY_ID = "target_entity_id"
ATTR_UNCHANGED = "unchanged"
ATTR_UPDATED = "updated"

CONF_LINKS = "links"

# A device that keeps failing to resolve is logged at debug level after this many
# consecutive failures, so a permanently missing device does not spam the log.
REAPPLY_FAILURE_LOG_LIMIT = 3
