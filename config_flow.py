"""Config flow for Sigenergy ESS integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_AC_CHARGER_COUNT,
    CONF_AC_CHARGER_SLAVE_IDS,
    CONF_DC_CHARGER_COUNT,
    CONF_DC_CHARGER_SLAVE_IDS,
    CONF_DEVICE_TYPE,
    CONF_INVERTER_COUNT,
    CONF_INVERTER_SLAVE_IDS,
    CONF_PARENT_DEVICE_ID,
    CONF_PLANT_ID,
    DEFAULT_AC_CHARGER_COUNT,
    DEFAULT_DC_CHARGER_COUNT,
    DEFAULT_INVERTER_COUNT,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SLAVE_ID,
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_NEW_PLANT,
    DEVICE_TYPE_PLANT,
    DOMAIN,
    STEP_AC_CHARGER_CONFIG,
    STEP_DC_CHARGER_CONFIG,
    STEP_DEVICE_TYPE,
    STEP_INVERTER_CONFIG,
    STEP_PLANT_CONFIG,
    STEP_SELECT_INVERTER,
    STEP_SELECT_PLANT,
    STEP_USER,
)

_LOGGER = logging.getLogger(__name__)

# Schema definitions for each step
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
    }
)

STEP_DEVICE_TYPE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_TYPE): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    {"value": DEVICE_TYPE_NEW_PLANT, "label": "New Plant"},
                    {"value": DEVICE_TYPE_INVERTER, "label": "Inverter"},
                    {"value": DEVICE_TYPE_AC_CHARGER, "label": "AC Charger"},
                    {"value": DEVICE_TYPE_DC_CHARGER, "label": "DC Charger"},
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)

STEP_PLANT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PLANT_ID, default=DEFAULT_SLAVE_ID): int,
        vol.Required(CONF_INVERTER_COUNT, default=DEFAULT_INVERTER_COUNT): int,
        vol.Required(CONF_AC_CHARGER_COUNT, default=DEFAULT_AC_CHARGER_COUNT): int,
    }
)

STEP_INVERTER_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_INVERTER_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

STEP_AC_CHARGER_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_AC_CHARGER_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

STEP_DC_CHARGER_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DC_CHARGER_COUNT, default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)


class SigenergyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Sigenergy ESS."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data = {}
        self._plants = {}
        self._inverters = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_USER, data_schema=STEP_USER_DATA_SCHEMA
            )

        # Store the basic connection information
        self._data.update(user_input)
        
        # Proceed to device type selection
        return await self.async_step_device_type()

    async def async_step_device_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle device type selection."""
        errors = {}

        # Check if any plants exist in the system
        await self._async_load_plants()
        has_plants = len(self._plants) > 0

        if user_input is None:
            return self.async_show_form(
                step_id=STEP_DEVICE_TYPE,
                data_schema=STEP_DEVICE_TYPE_SCHEMA,
                errors=errors
            )

        device_type = user_input[CONF_DEVICE_TYPE]
        self._data[CONF_DEVICE_TYPE] = device_type

        # If no plants exist and user selected something other than new plant,
        # override and force new plant creation first
        if not has_plants and device_type != DEVICE_TYPE_NEW_PLANT:
            self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_NEW_PLANT
            return await self.async_step_plant_config()

        # Route to appropriate next step based on device type
        if device_type == DEVICE_TYPE_NEW_PLANT:
            return await self.async_step_plant_config()
        elif device_type == DEVICE_TYPE_INVERTER:
            if len(self._plants) > 1:
                return await self.async_step_select_plant()
            elif len(self._plants) == 1:
                # Auto-connect to the only plant
                plant_id = list(self._plants.keys())[0]
                self._data[CONF_PARENT_DEVICE_ID] = plant_id
                return await self.async_step_inverter_config()
        elif device_type == DEVICE_TYPE_AC_CHARGER:
            if len(self._plants) > 1:
                return await self.async_step_select_plant()
            elif len(self._plants) == 1:
                # Auto-connect to the only plant
                plant_id = list(self._plants.keys())[0]
                self._data[CONF_PARENT_DEVICE_ID] = plant_id
                return await self.async_step_ac_charger_config()
        elif device_type == DEVICE_TYPE_DC_CHARGER:
            # Load inverters
            await self._async_load_inverters()
            if len(self._inverters) > 1:
                return await self.async_step_select_inverter()
            elif len(self._inverters) == 1:
                # Auto-connect to the only inverter
                inverter_id = list(self._inverters.keys())[0]
                self._data[CONF_PARENT_DEVICE_ID] = inverter_id
                return await self.async_step_dc_charger_config()
            else:
                errors["base"] = "no_inverters"
                return self.async_show_form(
                    step_id=STEP_DEVICE_TYPE,
                    data_schema=STEP_DEVICE_TYPE_SCHEMA,
                    errors=errors
                )

    async def async_step_plant_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle plant configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=STEP_PLANT_CONFIG_SCHEMA
            )

        # Store plant configuration
        self._data.update(user_input)
        
        # Generate inverter and AC charger slave IDs
        inverter_count = user_input[CONF_INVERTER_COUNT]
        ac_charger_count = user_input[CONF_AC_CHARGER_COUNT]
        
        inverter_slave_ids = list(range(1, inverter_count + 1))
        ac_charger_slave_ids = list(range(inverter_count + 1, inverter_count + ac_charger_count + 1))
        
        self._data[CONF_INVERTER_SLAVE_IDS] = inverter_slave_ids
        self._data[CONF_AC_CHARGER_SLAVE_IDS] = ac_charger_slave_ids
        self._data[CONF_DC_CHARGER_COUNT] = DEFAULT_DC_CHARGER_COUNT
        self._data[CONF_DC_CHARGER_SLAVE_IDS] = []
        
        # Create the configuration entry
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def async_step_inverter_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle inverter configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=STEP_INVERTER_CONFIG_SCHEMA
            )

        # Store inverter configuration
        self._data.update(user_input)
        
        # Generate inverter slave IDs
        inverter_count = user_input[CONF_INVERTER_COUNT]
        
        # Find the next available slave ID after existing inverters
        existing_slave_ids = []
        for entry_id, entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE) in [DEVICE_TYPE_PLANT, DEVICE_TYPE_NEW_PLANT]:
                existing_slave_ids.extend(entry.data.get(CONF_INVERTER_SLAVE_IDS, []))
            elif entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_INVERTER:
                existing_slave_ids.append(entry.data.get(CONF_SLAVE_ID, 0))
        
        # Start from the highest existing slave ID + 1
        start_slave_id = max(existing_slave_ids, default=0) + 1
        inverter_slave_ids = list(range(start_slave_id, start_slave_id + inverter_count))
        
        self._data[CONF_INVERTER_SLAVE_IDS] = inverter_slave_ids
        self._data[CONF_AC_CHARGER_COUNT] = DEFAULT_AC_CHARGER_COUNT
        self._data[CONF_AC_CHARGER_SLAVE_IDS] = []
        self._data[CONF_DC_CHARGER_COUNT] = DEFAULT_DC_CHARGER_COUNT
        self._data[CONF_DC_CHARGER_SLAVE_IDS] = []
        
        # Create the configuration entry
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def async_step_ac_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle AC charger configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=STEP_AC_CHARGER_CONFIG_SCHEMA
            )

        # Store AC charger configuration
        self._data.update(user_input)
        
        # Generate AC charger slave IDs
        ac_charger_count = user_input[CONF_AC_CHARGER_COUNT]
        
        # Find the next available slave ID after existing AC chargers
        existing_slave_ids = []
        for entry_id, entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE) in [DEVICE_TYPE_PLANT, DEVICE_TYPE_NEW_PLANT]:
                existing_slave_ids.extend(entry.data.get(CONF_AC_CHARGER_SLAVE_IDS, []))
            elif entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_AC_CHARGER:
                existing_slave_ids.append(entry.data.get(CONF_SLAVE_ID, 0))
        
        # Start from the highest existing slave ID + 1
        start_slave_id = max(existing_slave_ids, default=0) + 1
        ac_charger_slave_ids = list(range(start_slave_id, start_slave_id + ac_charger_count))
        
        self._data[CONF_AC_CHARGER_SLAVE_IDS] = ac_charger_slave_ids
        self._data[CONF_INVERTER_COUNT] = DEFAULT_INVERTER_COUNT
        self._data[CONF_INVERTER_SLAVE_IDS] = []
        self._data[CONF_DC_CHARGER_COUNT] = DEFAULT_DC_CHARGER_COUNT
        self._data[CONF_DC_CHARGER_SLAVE_IDS] = []
        
        # Create the configuration entry
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def async_step_dc_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle DC charger configuration."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_DC_CHARGER_CONFIG,
                data_schema=STEP_DC_CHARGER_CONFIG_SCHEMA
            )

        # Store DC charger configuration
        self._data.update(user_input)
        
        # Generate DC charger slave IDs
        dc_charger_count = user_input[CONF_DC_CHARGER_COUNT]
        
        # Find the next available slave ID after existing DC chargers
        existing_slave_ids = []
        for entry_id, entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE) in [DEVICE_TYPE_PLANT, DEVICE_TYPE_NEW_PLANT]:
                existing_slave_ids.extend(entry.data.get(CONF_DC_CHARGER_SLAVE_IDS, []))
            elif entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_DC_CHARGER:
                existing_slave_ids.append(entry.data.get(CONF_SLAVE_ID, 0))
        
        # Start from the highest existing slave ID + 1
        start_slave_id = max(existing_slave_ids, default=0) + 1
        dc_charger_slave_ids = list(range(start_slave_id, start_slave_id + dc_charger_count))
        
        self._data[CONF_DC_CHARGER_SLAVE_IDS] = dc_charger_slave_ids
        self._data[CONF_INVERTER_COUNT] = DEFAULT_INVERTER_COUNT
        self._data[CONF_INVERTER_SLAVE_IDS] = []
        self._data[CONF_AC_CHARGER_COUNT] = DEFAULT_AC_CHARGER_COUNT
        self._data[CONF_AC_CHARGER_SLAVE_IDS] = []
        
        # Create the configuration entry
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def async_step_select_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle plant selection."""
        if user_input is None:
            # Create a schema with a dropdown of available plants
            plants_schema = vol.Schema(
                {
                    vol.Required(CONF_PARENT_DEVICE_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": plant_id, "label": plant_name}
                                for plant_id, plant_name in self._plants.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
            return self.async_show_form(
                step_id=STEP_SELECT_PLANT,
                data_schema=plants_schema
            )

        # Store the selected plant
        self._data[CONF_PARENT_DEVICE_ID] = user_input[CONF_PARENT_DEVICE_ID]
        
        # Route to appropriate next step based on device type
        if self._data[CONF_DEVICE_TYPE] == DEVICE_TYPE_INVERTER:
            return await self.async_step_inverter_config()
        elif self._data[CONF_DEVICE_TYPE] == DEVICE_TYPE_AC_CHARGER:
            return await self.async_step_ac_charger_config()

    async def async_step_select_inverter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle inverter selection."""
        if user_input is None:
            # Create a schema with a dropdown of available inverters
            inverters_schema = vol.Schema(
                {
                    vol.Required(CONF_PARENT_DEVICE_ID): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": inverter_id, "label": inverter_name}
                                for inverter_id, inverter_name in self._inverters.items()
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            )
            return self.async_show_form(
                step_id=STEP_SELECT_INVERTER,
                data_schema=inverters_schema
            )

        # Store the selected inverter
        self._data[CONF_PARENT_DEVICE_ID] = user_input[CONF_PARENT_DEVICE_ID]
        
        # Proceed to DC charger configuration
        return await self.async_step_dc_charger_config()

    async def _async_load_plants(self) -> None:
        """Load existing plants from config entries."""
        self._plants = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE) in [DEVICE_TYPE_PLANT, DEVICE_TYPE_NEW_PLANT]:
                self._plants[entry.entry_id] = entry.data.get(CONF_NAME, f"Plant {entry.entry_id}")

    async def _async_load_inverters(self) -> None:
        """Load existing inverters from config entries."""
        self._inverters = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_INVERTER:
                self._inverters[entry.entry_id] = entry.data.get(CONF_NAME, f"Inverter {entry.entry_id}")