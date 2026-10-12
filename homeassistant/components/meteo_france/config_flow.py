"""Config flow to configure the Meteo-France integration."""

import logging
from typing import Any, override

from meteofrance_api.client import MeteoFranceClient
from meteofrance_api.model import Place
import probatio

from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.location import has_location
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import CONF_CITY, CONF_LOCATION_ENTITY, DOMAIN

_LOGGER = logging.getLogger(__name__)


class MeteoFranceFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a Meteo-France config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Init MeteoFranceFlowHandler."""
        self.places: list[Place] = []

    @callback
    def _show_setup_form(
        self,
        user_input: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Show the setup form to the user."""

        if user_input is None:
            user_input = {}

        return self.async_show_form(
            step_id="city",
            data_schema=probatio.Schema(
                {
                    probatio.Required(
                        CONF_CITY, default=user_input.get(CONF_CITY, "")
                    ): str
                }
            ),
            errors=errors or {},
        )

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        return self.async_show_menu(step_id="user", menu_options=["city", "entity"])

    async def async_step_city(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a fixed location searched by city name or postal code."""
        errors: dict[str, str] = {}

        if user_input is None:
            return self._show_setup_form(user_input, errors)

        city = user_input[CONF_CITY]  # Might be a city name or a postal code
        latitude = user_input.get(CONF_LATITUDE)
        longitude = user_input.get(CONF_LONGITUDE)

        if not latitude:
            client = MeteoFranceClient()
            self.places = await self.hass.async_add_executor_job(
                client.search_places, city
            )
            _LOGGER.debug("Places search result: %s", self.places)
            if not self.places:
                errors[CONF_CITY] = "empty"
                return self._show_setup_form(user_input, errors)

            return await self.async_step_cities()

        # Check if already configured
        await self.async_set_unique_id(f"{latitude}, {longitude}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=city,
            data={CONF_LATITUDE: latitude, CONF_LONGITUDE: longitude},
        )

    async def async_step_cities(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step where the user choose the city from the API search results."""
        if not user_input:
            if len(self.places) > 1 and self.source != SOURCE_IMPORT:
                places_for_form: dict[str, str] = {}
                for place in self.places:
                    places_for_form[_build_place_key(place)] = f"{place}"

                return self.async_show_form(
                    step_id="cities",
                    data_schema=probatio.Schema(
                        {
                            probatio.Required(CONF_CITY): probatio.All(
                                probatio.Coerce(str), probatio.In(places_for_form)
                            )
                        }
                    ),
                )
            user_input = {CONF_CITY: _build_place_key(self.places[0])}

        city_infos = user_input[CONF_CITY].split(";")
        return await self.async_step_city(
            {
                CONF_CITY: city_infos[0],
                CONF_LATITUDE: city_infos[1],
                CONF_LONGITUDE: city_infos[2],
            }
        )

    async def async_step_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a location following a person or device tracker."""
        errors: dict[str, str] = {}
        if user_input is not None:
            registry = er.async_get(self.hass)
            entity_entry = registry.async_get(user_input[CONF_LOCATION_ENTITY])
            if entity_entry is None:
                errors["base"] = "entity_not_found"
            elif entity_entry.disabled_by is not None:
                errors["base"] = "entity_disabled"
            elif (
                state := self.hass.states.get(entity_entry.entity_id)
            ) is None or not has_location(state):
                errors["base"] = "entity_no_coordinates"
            else:
                # Registry id keeps the entry valid if the entity is renamed
                await self.async_set_unique_id(entity_entry.id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=state.name, data={CONF_LOCATION_ENTITY: entity_entry.id}
                )

        return self.async_show_form(
            step_id="entity",
            data_schema=probatio.Schema(
                {
                    probatio.Required(CONF_LOCATION_ENTITY): EntitySelector(
                        EntitySelectorConfig(domain=["person", "device_tracker"])
                    )
                }
            ),
            errors=errors,
        )


def _build_place_key(place: Place) -> str:
    return f"{place};{place.latitude};{place.longitude}"
