"""Config flow for Sigenergy ESS integration."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import re
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_AC_CHARGER_SLAVE_ID,
    CONF_AC_CHARGER_CONNECTIONS,
    CONF_DC_CHARGER_CONNECTIONS,
    CONF_DEVICE_TYPE,
    CONF_INVERTER_SLAVE_ID,
    CONF_INVERTER_CONNECTIONS,
    CONF_PARENT_INVERTER_ID,
    CONF_PARENT_PLANT_ID,
    CONF_PLANT_ID,
    CONF_SLAVE_ID,
    DEFAULT_PORT,
    DEFAULT_PLANT_SLAVE_ID,
    DEFAULT_INVERTER_SLAVE_ID,
    DEVICE_TYPE_NEW_PLANT,
    DEVICE_TYPE_PLANT,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DOMAIN,
    STEP_DEVICE_TYPE,
    STEP_PLANT_CONFIG,
    STEP_INVERTER_CONFIG,
    STEP_AC_CHARGER_CONFIG,
    STEP_SELECT_PLANT,
    STEP_SELECT_INVERTER,
    DEFAULT_READ_ONLY,
)

# Define constants that might not be in the .const module
CONF_READ_ONLY = "read_only"
CONF_REMOVE_DEVICE = "remove_device"

STEP_DC_CHARGER_CONFIG = "dc_charger_config"
STEP_SELECT_DEVICE = "select_device"
STEP_RECONFIGURE = "reconfigure"


_LOGGER = logging.getLogger(__name__)

# Schema definitions for each step
STEP_DEVICE_TYPE_SCHEMA = vol.Schema(
    {
        vol.Required("device_type"): vol.In(
            {
                DEVICE_TYPE_NEW_PLANT: "New Plant",
                DEVICE_TYPE_INVERTER: "Inverter",
                DEVICE_TYPE_AC_CHARGER: "AC Charger",
                DEVICE_TYPE_DC_CHARGER: "DC Charger",
            }
        ),
    }
)

STEP_PLANT_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_INVERTER_SLAVE_ID, default=DEFAULT_INVERTER_SLAVE_ID): int,
        vol.Required(CONF_READ_ONLY, default=DEFAULT_READ_ONLY): bool,
    }
)

STEP_INVERTER_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SLAVE_ID, default=DEFAULT_INVERTER_SLAVE_ID): int,
    }
)

STEP_AC_CHARGER_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SLAVE_ID): int,
    }
)

STEP_DC_CHARGER_CONFIG_SCHEMA = vol.Schema({})

def validate_host_port(host: str, port: int) -> Dict[str, str]:
    """Validate host and port combination.
    
    Args:
        host: The host address
        port: The port number
        
    Returns:
        Dictionary of errors, empty if validation passes
    """
    errors = {}
    
    if host is None or host == "":
        errors["host"] = "invalid_host"
    
    if not port or not (1 <= port <= 65535):
        errors["port"] = "invalid_port"
        
    return errors

def validate_slave_id(
    slave_id: int, 
    existing_ids: List[int] = [],
    field_name: str = CONF_SLAVE_ID
,
) -> Dict[str, str]:
    """Validate a slave ID."""
    errors = {}
    
    if slave_id is None or not (1 <= slave_id <= 246):
        errors[field_name] = "each_id_must_be_between_1_and_246"
    elif existing_ids and slave_id in existing_ids:
        errors[field_name] = "duplicate_ids_found"
        
    return errors

def validate_slave_ids(raw_ids: str, field_name: str) -> Tuple[List[int], Dict[str, str]]:
    """Validate slave IDs from a comma-separated string.
    
    Returns:
        Tuple containing list of valid IDs and dict of errors (if any)
        An empty string input will return an empty list with no errors.
    """
    errors = {}
    id_list = []
    
    # Skip validation for empty strings (indicating no devices of this type)
    if not raw_ids or raw_ids.strip() == "":
        return [], errors
    
    for part in raw_ids.split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            val = int(part)
            if not (1 <= val <= 246):
                errors[field_name] = "each_id_must_be_between_1_and_246"
                break
            id_list.append(val)
        else:
            errors[field_name] = "invalid_integer_value"
            break
            
    # Check for duplicate IDs
    if not errors and not _LOGGER.isEnabledFor(logging.DEBUG):
        if len(set(id_list)) != len(id_list):
            errors[field_name] = "duplicate_ids_found"
            
    return id_list, errors

@config_entries.HANDLERS.register(DOMAIN)
class SigenergyConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for Sigenergy ESS."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data = {}
        self._plants = {}
        self._inverters = {}
        self._devices = {}
        self._selected_plant_entry_id = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step when adding a new device."""
        # Load existing plants
        await self._async_load_plants()
        
        # If no plants exist, go directly to plant configuration
        if not self._plants:
            self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_NEW_PLANT
            return await self.async_step_plant_config()
        
        # Otherwise, show device type selection
        return await self.async_step_device_type()
        
    async def async_step_device_type(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the device type selection when adding a new device."""
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_DEVICE_TYPE,
                data_schema=STEP_DEVICE_TYPE_SCHEMA,
            )
        
        device_type = user_input["device_type"]
        self._data[CONF_DEVICE_TYPE] = device_type
        
        if device_type == DEVICE_TYPE_NEW_PLANT:
            return await self.async_step_plant_config()
        elif device_type in [DEVICE_TYPE_INVERTER, DEVICE_TYPE_AC_CHARGER, DEVICE_TYPE_DC_CHARGER]:
            return await self.async_step_select_plant()
        
        # Should never reach here
        return self.async_abort(reason="unknown_device_type")
    
    async def async_step_plant_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the plant configuration step when adding a new plant device."""
        errors = {}
        
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=STEP_PLANT_CONFIG_SCHEMA
            )

        # Store plant configuration
        self._data.update(user_input)
        
        # Always use the default plant ID (247)
        self._data[CONF_PLANT_ID] = DEFAULT_PLANT_SLAVE_ID

        # Process and validate inverter ID
        try:
            inverter_id = int(user_input[CONF_INVERTER_SLAVE_ID])
            if not (1 <= inverter_id <= 246):
                errors[CONF_INVERTER_SLAVE_ID] = "each_id_must_be_between_1_and_246"
            elif not _LOGGER.isEnabledFor(logging.DEBUG):
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_INVERTER:
                        existing_id = entry.data.get(CONF_INVERTER_SLAVE_ID)
                        if existing_id and inverter_id in existing_id:
                            errors[CONF_INVERTER_SLAVE_ID] = "duplicate_ids_found"
                            break
        except (ValueError, TypeError):
            errors[CONF_INVERTER_SLAVE_ID] = "invalid_integer_value"
            
        if errors:
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=STEP_PLANT_CONFIG_SCHEMA,
                errors=errors
            )

        # Store the validated lists
        self._data[CONF_INVERTER_SLAVE_ID] = [inverter_id]
        self._data[CONF_AC_CHARGER_SLAVE_ID] = []
        self._data[CONF_DC_CHARGER_CONNECTIONS] = {}


        # Create the inverter connections dictionary for the implicit first inverter
        inverter_name = "Inverter 1"
        self._data[CONF_INVERTER_CONNECTIONS] = {
            inverter_name: {
                CONF_HOST: self._data[CONF_HOST],
                CONF_PORT: self._data[CONF_PORT],
                CONF_SLAVE_ID: inverter_id
            }
        }
        
        # Store the plant name generated based on the number of installed plants
        plant_no = len(self._plants)
        self._data[CONF_NAME] = f"Sigen{' ' if plant_no == 0 else f' {plant_no} '}Plant"
        
        # Set the device type as plant
        self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_PLANT

        # Create the configuration entry with the default name
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)
    
    async def async_step_select_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the plant selection step when adding a new child device."""
        if not self._plants:
            # No plants available, abort with error
            return self.async_abort(reason="no_plants_available")
        
        if user_input is None:
            # Create schema with plant selection
            schema = vol.Schema({
                vol.Required(CONF_PARENT_PLANT_ID): vol.In(self._plants)
            })
            
            return self.async_show_form(
                step_id=STEP_SELECT_PLANT,
                data_schema=schema,
            )
        
        # Store the selected plant ID
        self._selected_plant_entry_id = user_input[CONF_PARENT_PLANT_ID]
        self._data[CONF_PARENT_PLANT_ID] = self._selected_plant_entry_id
        
        # Get the plant entry to access its configuration
        _LOGGER.debug("Selected plant entry ID: %s", self._selected_plant_entry_id)
        plant_entry = self.hass.config_entries.async_get_entry(self._selected_plant_entry_id)
        if plant_entry:
            # Copy host and port from the plant
            self._data[CONF_HOST] = plant_entry.data.get(CONF_HOST)
            self._data[CONF_PORT] = plant_entry.data.get(CONF_PORT)
        
        # Proceed based on the device type
        device_type = self._data.get(CONF_DEVICE_TYPE)
        
        if device_type == DEVICE_TYPE_INVERTER:
            return await self.async_step_inverter_config()
        elif device_type == DEVICE_TYPE_AC_CHARGER:
            return await self.async_step_ac_charger_config()
        elif device_type == DEVICE_TYPE_DC_CHARGER:
            # For DC Charger, we need to load inverters from the selected plant
            await self._async_load_inverters(self._selected_plant_entry_id)
            return await self.async_step_select_inverter()
        
        # Should never reach here
        return self.async_abort(reason="unknown_device_type")
    async def async_step_inverter_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the inverter configuration step when adding a new inverter device."""
        errors = {}
        
        if user_input is None:
            schema = STEP_INVERTER_CONFIG_SCHEMA
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
            )
        
        # Validate the slave ID
        slave_id = user_input.get(CONF_SLAVE_ID)
        if slave_id is None or not (1 <= slave_id <= 246):
            errors[CONF_SLAVE_ID] = "each_id_must_be_between_1_and_246"
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=STEP_INVERTER_CONFIG_SCHEMA,
                errors=errors,
            )
            
        # Check for duplicate IDs
        plant_entry = self.hass.config_entries.async_get_entry(self._selected_plant_entry_id)
        if plant_entry:
            plant_inverters = plant_entry.data.get(CONF_INVERTER_SLAVE_ID, [])
            if slave_id in plant_inverters and not _LOGGER.isEnabledFor(logging.DEBUG):
                errors[CONF_SLAVE_ID] = "duplicate_ids_found"
                return self.async_show_form(
                    step_id=STEP_INVERTER_CONFIG,
                    data_schema=STEP_INVERTER_CONFIG_SCHEMA,
                    errors=errors,
                )
            
            # Get the inverter name based on number of existing inverters
            inverter_no = len(plant_inverters)
            inverter_name = f"Inverter{' ' if inverter_no == 0 else f' {inverter_no + 1} '}"
            
            # Create or update the inverter connections dictionary
            new_data = dict(plant_entry.data)
            inverter_connections = new_data.get(CONF_INVERTER_CONNECTIONS, {})
            inverter_connections[inverter_name] = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: slave_id
            }
            
            # Update the plant's configuration with the new inverter
            new_data[CONF_INVERTER_SLAVE_ID] = plant_inverters + [slave_id]
            new_data[CONF_INVERTER_CONNECTIONS] = inverter_connections
            
            self.hass.config_entries.async_update_entry(
                plant_entry,
                data=new_data
            )
            
            return self.async_abort(reason="device_added")
            
        return self.async_abort(reason="parent_plant_not_found")
    
    async def async_step_ac_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the AC charger configuration step when adding a new AC charger device."""
        errors = {}
        
        if user_input is None:
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=STEP_AC_CHARGER_CONFIG_SCHEMA,
            )
        
        # Validate the slave ID
        slave_id = user_input.get(CONF_SLAVE_ID)
        if slave_id is None or not (1 <= slave_id <= 246):
            errors[CONF_SLAVE_ID] = "each_id_must_be_between_1_and_246"
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=STEP_AC_CHARGER_CONFIG_SCHEMA,
                errors=errors,
            )
            
        # Check for duplicate IDs and conflicts with inverters
        plant_entry = self.hass.config_entries.async_get_entry(self._selected_plant_entry_id)
        if plant_entry:
            plant_ac_chargers = plant_entry.data.get(CONF_AC_CHARGER_SLAVE_ID, [])
            plant_inverters = plant_entry.data.get(CONF_INVERTER_SLAVE_ID, [])
            
            if slave_id in plant_ac_chargers:
                errors[CONF_SLAVE_ID] = "duplicate_ids_found"
            elif slave_id in plant_inverters:
                errors[CONF_SLAVE_ID] = "ac_charger_conflicts_inverter"
                
            if errors:
                return self.async_show_form(
                    step_id=STEP_AC_CHARGER_CONFIG,
                    data_schema=STEP_AC_CHARGER_CONFIG_SCHEMA,
                    errors=errors,
                )
            
            # Get the AC charger name based on number of existing AC chargers
            ac_charger_no = len(plant_ac_chargers)
            ac_charger_name = f"AC Charger{' ' if ac_charger_no == 0 else f' {ac_charger_no + 1} '}"
            
            # Create or update the AC charger connections dictionary
            new_data = dict(plant_entry.data)
            ac_charger_connections = new_data.get(CONF_AC_CHARGER_CONNECTIONS, {})
            ac_charger_connections[ac_charger_name] = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: slave_id
            }
            
            # Update the plant's configuration with the new AC charger
            new_data[CONF_AC_CHARGER_SLAVE_ID] = plant_ac_chargers + [slave_id]
            new_data[CONF_AC_CHARGER_CONNECTIONS] = ac_charger_connections
            
            self.hass.config_entries.async_update_entry(
                plant_entry,
                data=new_data
            )
            
            return self.async_abort(reason="device_added")
            
        return self.async_abort(reason="parent_plant_not_found")
    
    async def async_step_select_inverter(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the inverter selection step when adding a new DC charger device."""
        if not self._inverters:
            # No inverters available, abort with error
            return self.async_abort(reason="no_inverters_available")
        
        if user_input is None:
            # Create schema with inverter selection
            schema = vol.Schema({
                vol.Required(CONF_PARENT_INVERTER_ID): vol.In(self._inverters)
            })
            
            return self.async_show_form(
                step_id=STEP_SELECT_INVERTER,
                data_schema=schema,
            )
        
        # Get the plant data
        plant_entry = self.hass.config_entries.async_get_entry(self._selected_plant_entry_id)
        if not plant_entry:
            return self.async_abort(reason="parent_plant_not_found")

        # Get the inverter connections
        inverter_connections = plant_entry.data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug("Inverter connections: %s", inverter_connections)

        # Get the selected inverter connection details
        selected_inverter = user_input[CONF_PARENT_INVERTER_ID]
        inverter_details = list(inverter_connections.values())[selected_inverter]
        _LOGGER.debug("Selected inverter: %s, details: %s", selected_inverter, inverter_details)

        if not inverter_details:
            return self.async_abort(reason="inverter_details_not_found")

        # Get the slave ID and host and verify it exists
        inverter_slave_id = inverter_details.get(CONF_SLAVE_ID)
        inverter_host = inverter_details.get(CONF_HOST)
        inverter_port = inverter_details.get(CONF_PORT)
        # inverter_slave_id = inverter_entry.data.get(CONF_SLAVE_ID)
        if not inverter_slave_id:
            _LOGGER.debug("Inverter slave ID not found in details: %s", inverter_details)
            return self.async_abort(reason="parent_inverter_invalid")
        
        if not inverter_host:
            _LOGGER.debug("Inverter host not found in details: %s", inverter_details)
            return self.async_abort(reason="parent_inverter_host_not_found")
        
        # Validate the host and port
        host_port_errors = validate_host_port(inverter_host, inverter_port)
        if host_port_errors:
            _LOGGER.debug("Host/port validation errors: %s", host_port_errors)
            return self.async_abort(reason="invalid_host_or_port")
            
        # Check for existing DC charger with this ID
        plant_entry = self.hass.config_entries.async_get_entry(self._selected_plant_entry_id)
        if plant_entry:
            # Get existing DC charger connections and extract their slave IDs
            dc_charger_connections_existing = plant_entry.data.get(CONF_DC_CHARGER_CONNECTIONS, {})
            plant_dc_charger_ids = [details.get(CONF_SLAVE_ID) for details in dc_charger_connections_existing.values() if details.get(CONF_SLAVE_ID) is not None]

            if inverter_slave_id in plant_dc_charger_ids:
                return self.async_abort(reason="duplicate_ids_found")

            # Update the plant's configuration with the new DC charger
            new_data = dict(plant_entry.data)

            # Create or update the DC charger connections dictionary
            dc_charger_connections = new_data.get(CONF_DC_CHARGER_CONNECTIONS, {})
            dc_charger_name = f"DC Charger {len(dc_charger_connections) + 1}"
            dc_charger_connections[dc_charger_name] = {
                CONF_HOST: inverter_host,
                CONF_PORT: inverter_port,
                CONF_SLAVE_ID: inverter_slave_id
            }
            new_data[CONF_DC_CHARGER_CONNECTIONS] = dc_charger_connections
            
            self.hass.config_entries.async_update_entry(
                plant_entry,
                data=new_data
            )
            
            return self.async_abort(reason="device_added")
            
        return self.async_abort(reason="parent_plant_not_found")

    async def _async_load_plants(self) -> None:
        """Load existing plants from config entries when adding a new device."""
        self._plants = {}
        
        # Log the number of config entries for debugging
        _LOGGER.debug("Total config entries: %s", len(self.hass.config_entries.async_entries(DOMAIN)))
        
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            # Log each entry to see what's being found
            _LOGGER.debug("Found entry: %s, device type: %s", 
                        entry.entry_id, 
                        entry.data.get(CONF_DEVICE_TYPE))
                        
            if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_PLANT:
                self._plants[entry.entry_id] = entry.data.get(CONF_NAME, f"Plant {entry.entry_id}")
                
        # Log the plants that were found
        _LOGGER.debug("Found plants: %s", self._plants)
    
    async def _async_load_inverters(self, plant_entry_id: str) -> None:
        """Load existing inverters for a specific plant when adding a new DC charger device."""
        self._inverters = {}

        plant_entry = self.hass.config_entries.async_get_entry(plant_entry_id)
        if not plant_entry:
            _LOGGER.error("SigenergyConfigFlow.async_load_inverters: No plant entry found for ID: %s", plant_entry_id)
            return
        plant_data = dict(plant_entry.data)
        inverter_connections = plant_data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug("Inverter connections: %s", inverter_connections)
        
        # Process inverters with special handling for the first implicit inverter
        for i, (inv_name, inv_details) in enumerate(inverter_connections.items()):
            device_key = f"inverter_{inv_name}"
            # self._inverters[i] = inv_name, inv_details
            # For first inverter (implicit), remove the number and include host/ID info
            if i == 0:
                device_key = "inverter"
                display_name = f"Inverter (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"
            else:
                device_key = display_name.replace(" ", "_").lower()
                display_name = f"{inv_name} (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"
            
            self._inverters[i] = display_name
            _LOGGER.debug("Added inverter device: %s -> %s", i, self._inverters[i])
        

        # for entry in self.hass.config_entries.async_entries(DOMAIN):
        #     _LOGGER.debug("SigenergyConfigFlow.async_load_inverters: Found entry: %s, device type: %s, parent plant ID: %s",
        #                 entry.entry_id, 
        #                 entry.data.get(CONF_DEVICE_TYPE), 
        #                 entry.data.get(CONF_PARENT_PLANT_ID))
        #     if (entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_INVERTER and
        #         entry.data.get(CONF_PARENT_PLANT_ID) == plant_entry_id):
        #         self._inverters[entry.entry_id] = entry.data.get(CONF_NAME, f"Inverter {entry.entry_id}")
        #         _LOGGER.debug("SigenergyConfigFlow.async_load_inverters: Found inverter: %s", self._inverters[entry.entry_id])
        
        _LOGGER.debug("Found inverters for plant %s: %s", plant_entry_id, self._inverters)

    def _create_reconfigure_schema(self, inv_ids=""):
        """Create schema with default or provided values when adding a new device."""
        # Use provided values or get current values from data
        if not inv_ids:
            current_ids = self._data.get(CONF_INVERTER_SLAVE_ID, [])
            inv_ids = ", ".join(str(i) for i in current_ids) if current_ids else ""
        
        return vol.Schema({
            vol.Required(CONF_INVERTER_SLAVE_ID, default=inv_ids): str,
        })

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return SigenergyOptionsFlowHandler(config_entry)

class SigenergyOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Sigenergy options for reconfiguring existing devices."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.options = dict(config_entry.options)
        self._data = dict(config_entry.data)
        self._plants = {}
        self._devices = {}
        self._inverters = {}
        self._devices_loaded = False
        self._selected_device = None
        self._temp_config = {}

    async def _async_load_devices(self) -> None:
        """Load all existing devices for reconfiguration selection."""
        self._devices = {}
        device_type = self._data.get(CONF_DEVICE_TYPE)
        _LOGGER.debug("Loading devices for device type: %s", device_type)
        
        if device_type == DEVICE_TYPE_PLANT:
            # For plants, load all child devices
            plant_entry_id = self.config_entry.entry_id
            plant_name = self._data.get(CONF_NAME, f"Plant {plant_entry_id}")
            plant_host = self._data.get(CONF_HOST, "")
            
            # Add the plant itself with host info
            self._devices[f"plant_{plant_entry_id}"] = f"{plant_name} (Host: {plant_host})"
            
            # Add inverters
            inverter_connections = self._data.get(CONF_INVERTER_CONNECTIONS, {})
            _LOGGER.debug("Inverter connections: %s", inverter_connections)
            
            # Process inverters with special handling for the first implicit inverter
            for i, (inv_name, inv_details) in enumerate(inverter_connections.items()):
                device_key = f"inverter_{inv_name}"
                
                # For first inverter (implicit), remove the number and include host/ID info
                if i == 0:
                    display_name = f"Inverter (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"
                else:
                    display_name = f"{inv_name} (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"
                
                self._devices[device_key] = display_name
                _LOGGER.debug("Added inverter device: %s -> %s", device_key, self._devices[device_key])
            
            # Add AC chargers with host info
            ac_charger_connections = self._data.get(CONF_AC_CHARGER_CONNECTIONS, {})
            for ac_name, ac_details in ac_charger_connections.items():
                self._devices[f"ac_charger_{ac_name}"] = f"{ac_name} (Host: {ac_details.get(CONF_HOST)}, ID: {ac_details.get(CONF_SLAVE_ID)})"
            
            # Add DC chargers
            dc_charger_connections = self._data.get(CONF_DC_CHARGER_CONNECTIONS, {})
            for dc_name, dc_details in dc_charger_connections.items():
                dc_id = dc_details.get(CONF_SLAVE_ID)
                if dc_id is not None:
                    self._devices[f"dc_charger_{dc_id}"] = f"{dc_name} (ID: {dc_id})"
        
        self._devices_loaded = True
        
        _LOGGER.debug("Loaded devices for selection: %s", self._devices)

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Initial handler for device reconfiguration options."""
        device_type = self._data.get(CONF_DEVICE_TYPE)
        _LOGGER.debug("Options flow init for device type: %s", device_type)
        
        # If this is a plant, load devices and show device selection
        if device_type == DEVICE_TYPE_PLANT and not self._devices_loaded:
            await self._async_load_devices()
            return await self.async_step_select_device()
        
        # For non-plant devices or if no devices loaded, go to device-specific options
        if device_type == DEVICE_TYPE_PLANT:
            return await self.async_step_plant_config(user_input)
        elif device_type == DEVICE_TYPE_INVERTER:
            return await self.async_step_inverter_config(user_input)
        elif device_type == DEVICE_TYPE_AC_CHARGER:
            return await self.async_step_ac_charger_config(user_input)
        elif device_type == DEVICE_TYPE_DC_CHARGER:
            return await self.async_step_dc_charger_config(user_input)
        
        # Fallback
        return self.async_abort(reason="unknown_device_type")
    
    async def async_step_select_device(self, user_input: dict[str, Any] | None = None):
        """Handle selection of which existing device to reconfigure."""
        if not self._devices:
            _LOGGER.debug("No devices available for selection, going to plant config")
            return await self.async_step_plant_config()
        
        if user_input is None:
            # Create schema with device selection
            schema = vol.Schema({
                vol.Required("selected_device"): vol.In(self._devices)
            })
            
            return self.async_show_form(
                step_id=STEP_SELECT_DEVICE,
                data_schema=schema,
            )
        
        # Parse the selected device
        _LOGGER.debug("Selected device: %s", user_input["selected_device"])
        selected_device = user_input.get("selected_device", "")
        device_parts = selected_device.split("_", 1)
        
        if len(device_parts) < 2:
            return self.async_abort(reason="invalid_device_selection")
        
        device_type = device_parts[0]
        device_id = device_parts[1]
        
        # Store the selected device info
        self._selected_device = {
            "type": device_type,
            "id": device_id
        }
        _LOGGER.debug("Parsed selected device: %s", self._selected_device)

        # Store the selected device for later use
        self._temp_config["selected_device"] = self._selected_device
        
        # Route to the appropriate configuration step
        if device_type == "plant":
            return await self.async_step_plant_config()
        elif device_type == "inverter":
            return await self.async_step_inverter_config()
        elif device_type == "ac_charger":
            return await self.async_step_ac_charger_config()
        elif device_type == "dc_charger":
            return await self.async_step_dc_charger_config()
        
        # Fallback
        return self.async_abort(reason="unknown_device_type")
    
    async def async_step_plant_config(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of an existing plant device."""
        errors = {}
        
        if user_input is None:
            # Create schema with current values
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=self._data.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=self._data.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_READ_ONLY, default=self._data.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=schema,
            )
        
        # Validate host and port
        host_port_errors = validate_host_port(user_input.get(CONF_HOST, ""), user_input.get(CONF_PORT, 0))
        errors.update(host_port_errors)
        
        if errors:
            # Re-create schema with user input values for error display
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_READ_ONLY, default=user_input.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=schema,
                errors=errors,
            )
        
        # Update the configuration entry with the new data
        new_data = dict(self._data)
        new_data[CONF_HOST] = user_input[CONF_HOST]
        new_data[CONF_PORT] = user_input[CONF_PORT]
        new_data[CONF_READ_ONLY] = user_input[CONF_READ_ONLY]
        
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )
        
        return self.async_create_entry(title="", data={})
    
    async def async_step_inverter_config(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of an existing inverter device."""
        errors = {}
        
        # Get the inverter details
        inverter_name = self._selected_device["id"] if self._selected_device else None
        inverter_connections = self._data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug("Inverter name: %s, connections: %s", inverter_name, inverter_connections)
        inverter_details = inverter_connections.get(inverter_name, {})
        
        if user_input is None:
            # Create schema with current values
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=inverter_details.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=inverter_details.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_SLAVE_ID, default=inverter_details.get(CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID)): int,
                vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
            )
        
        # Check if user wants to remove the device
        if user_input.get(CONF_REMOVE_DEVICE, False):
            # Validate that the inverter can be removed
            # Check if the inverter's slave ID is used by any DC charger connection
            dc_charger_connections = self._data.get(CONF_DC_CHARGER_CONNECTIONS, {})
            dc_charger_slave_ids = [details.get(CONF_SLAVE_ID) for details in dc_charger_connections.values() if details.get(CONF_SLAVE_ID) is not None]
            inverter_slave_id = inverter_details.get(CONF_SLAVE_ID)
            
            if inverter_slave_id in dc_charger_slave_ids:
                errors[CONF_REMOVE_DEVICE] = "cannot_remove_parent"
                
                # Re-create schema with error
                schema = vol.Schema({
                    vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                    vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
                    vol.Required(CONF_SLAVE_ID, default=user_input.get(CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID)): int,
                    vol.Optional(CONF_REMOVE_DEVICE, default=True): bool,
                })
                
                return self.async_show_form(
                    step_id=STEP_INVERTER_CONFIG,
                    data_schema=schema,
                    errors=errors,
                )
            
            # Remove the inverter
            new_data = dict(self._data)
            
            # Remove from inverter connections
            new_inverter_connections = dict(inverter_connections)
            if inverter_name in new_inverter_connections:
                del new_inverter_connections[inverter_name]
            new_data[CONF_INVERTER_CONNECTIONS] = new_inverter_connections
            
            # Remove from inverter slave IDs
            inverter_slave_ids = new_data.get(CONF_INVERTER_SLAVE_ID, [])
            if inverter_slave_id in inverter_slave_ids:
                inverter_slave_ids.remove(inverter_slave_id)
            new_data[CONF_INVERTER_SLAVE_ID] = inverter_slave_ids
            
            # Update the configuration entry
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            
            return self.async_create_entry(title="", data={})
        
        # Validate host, port, and slave ID
        host_port_errors = validate_host_port(user_input.get(CONF_HOST, ""), user_input.get(CONF_PORT, 0))
        errors.update(host_port_errors)
        
        # Validate slave ID
        slave_id = user_input.get(CONF_SLAVE_ID)
        existing_ids = []
        
        # Get existing slave IDs excluding the current one
        for name, details in inverter_connections.items():
            if name != inverter_name:
                existing_ids.append(details.get(CONF_SLAVE_ID))
        
        slave_id_errors = validate_slave_id(slave_id or 0, existing_ids)
        errors.update(slave_id_errors or {})
        
        if errors:
            # Re-create schema with user input values for error display
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_SLAVE_ID, default=user_input.get(CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID)): int,
                vol.Optional(CONF_REMOVE_DEVICE, default=user_input.get(CONF_REMOVE_DEVICE, False)): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
                errors=errors,
            )
        
        # Update the inverter configuration
        new_data = dict(self._data)
        new_inverter_connections = dict(inverter_connections)
        
        # Update the inverter details
        new_inverter_connections[inverter_name] = {
            CONF_HOST: user_input[CONF_HOST],
            CONF_PORT: user_input[CONF_PORT],
            CONF_SLAVE_ID: slave_id
        }
        
        # Update the configuration entry
        new_data[CONF_INVERTER_CONNECTIONS] = new_inverter_connections
        
        # Update the inverter slave IDs if changed
        old_slave_id = inverter_details.get(CONF_SLAVE_ID)
        if old_slave_id != slave_id:
            inverter_slave_ids = new_data.get(CONF_INVERTER_SLAVE_ID, [])
            if old_slave_id in inverter_slave_ids:
                inverter_slave_ids.remove(old_slave_id)
            inverter_slave_ids.append(slave_id)
            new_data[CONF_INVERTER_SLAVE_ID] = inverter_slave_ids
        
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )
        
        return self.async_create_entry(title="", data={})
    
    async def async_step_ac_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of an existing AC charger device."""
        errors = {}
        
        # Get the AC charger details
        ac_charger_name = self._selected_device["id"] if self._selected_device else None
        ac_charger_connections = self._data.get(CONF_AC_CHARGER_CONNECTIONS, {})
        ac_charger_details = ac_charger_connections.get(ac_charger_name, {})
        
        if user_input is None:
            # Create schema with current values
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=ac_charger_details.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=ac_charger_details.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_SLAVE_ID, default=ac_charger_details.get(CONF_SLAVE_ID, 1)): int,
                vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=schema,
            )
        
        # Check if user wants to remove the device
        if user_input.get(CONF_REMOVE_DEVICE, False):
            # Remove the AC charger
            new_data = dict(self._data)
            
            # Remove from AC charger connections
            new_ac_charger_connections = dict(ac_charger_connections)
            if ac_charger_name in new_ac_charger_connections:
                del new_ac_charger_connections[ac_charger_name]
            new_data[CONF_AC_CHARGER_CONNECTIONS] = new_ac_charger_connections
            
            # Remove from AC charger slave IDs
            ac_charger_slave_id = ac_charger_details.get(CONF_SLAVE_ID)
            ac_charger_slave_ids = new_data.get(CONF_AC_CHARGER_SLAVE_ID, [])
            if ac_charger_slave_id in ac_charger_slave_ids:
                ac_charger_slave_ids.remove(ac_charger_slave_id)
            new_data[CONF_AC_CHARGER_SLAVE_ID] = ac_charger_slave_ids
            
            # Update the configuration entry
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            
            return self.async_create_entry(title="", data={})
        
        # Validate host, port, and slave ID
        host_port_errors = validate_host_port(user_input.get(CONF_HOST, ""), user_input.get(CONF_PORT, 0))
        errors.update(host_port_errors)
        
        # Validate slave ID
        slave_id = user_input.get(CONF_SLAVE_ID)
        existing_ids = []
        
        # Get existing AC charger slave IDs excluding the current one
        for name, details in ac_charger_connections.items():
            if name != ac_charger_name:
                existing_ids.append(details.get(CONF_SLAVE_ID))
        
        # Also check for conflicts with inverter IDs
        inverter_slave_ids = self._data.get(CONF_INVERTER_SLAVE_ID, [])
        
        slave_id_errors = validate_slave_id(slave_id or 0, existing_ids)
        errors.update(slave_id_errors or {})
        
        # Check for conflicts with inverter IDs
        if not errors and slave_id in inverter_slave_ids:
            errors[CONF_SLAVE_ID] = "ac_charger_conflicts_inverter"
        
        if errors:
            # Re-create schema with user input values for error display
            schema = vol.Schema({
                vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_SLAVE_ID, default=user_input.get(CONF_SLAVE_ID, 1)): int,
                vol.Optional(CONF_REMOVE_DEVICE, default=user_input.get(CONF_REMOVE_DEVICE, False)): bool,
            })
                
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=schema,
                errors=errors,
            )
        
        # Update the AC charger configuration
        new_data = dict(self._data)
        new_ac_charger_connections = dict(ac_charger_connections)
        
        # Update the AC charger details
        new_ac_charger_connections[ac_charger_name] = {
            CONF_HOST: user_input[CONF_HOST],
            CONF_PORT: user_input[CONF_PORT],
            CONF_SLAVE_ID: slave_id
        }
        
        # Update the configuration entry
        new_data[CONF_AC_CHARGER_CONNECTIONS] = new_ac_charger_connections
        
        # Update the AC charger slave IDs if changed
        old_slave_id = ac_charger_details.get(CONF_SLAVE_ID)
        if old_slave_id != slave_id:
            ac_charger_slave_ids = new_data.get(CONF_AC_CHARGER_SLAVE_ID, [])
            if old_slave_id in ac_charger_slave_ids:
                ac_charger_slave_ids.remove(old_slave_id)
            ac_charger_slave_ids.append(slave_id)
            new_data[CONF_AC_CHARGER_SLAVE_ID] = ac_charger_slave_ids
        
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=new_data
        )
        
        return self.async_create_entry(title="", data={})

    async def async_step_dc_charger_config(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of an existing DC charger device."""
        errors = {}
        
        # Get the DC charger details
        dc_charger_id = self._selected_device["id"] if self._selected_device else None
        dc_charger_slave_id = int(dc_charger_id) if dc_charger_id and dc_charger_id.isdigit() else None
        
        if user_input is None:
            # Load inverters for selection
            inverters = {}
            inverter_connections = self._data.get(CONF_INVERTER_CONNECTIONS, {})
            
            for inv_name, inv_details in inverter_connections.items():
                inverters[inv_name] = f"{inv_name} (Slave ID: {inv_details.get(CONF_SLAVE_ID)})"
            
            # Create schema with current values and inverter selection
            schema = vol.Schema({
                vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
            })
            
            return self.async_show_form(
                step_id=STEP_DC_CHARGER_CONFIG,
                data_schema=schema,
            )

        
        # Check if user wants to remove the device
        if user_input.get(CONF_REMOVE_DEVICE, False):
            # Remove the DC charger
            new_data = dict(self._data)
            
            # Update the configuration entry
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            
            return self.async_create_entry(title="", data={})
        return self.async_create_entry(title="", data={})

    def _create_reconfigure_schema(self, inv_ids: str = "") -> vol.Schema:
        """Create schema for reconfiguring device IDs with default or provided values."""
        if not inv_ids:
            current_ids = self._data.get(CONF_INVERTER_SLAVE_ID, [])
            inv_ids = ", ".join(str(i) for i in current_ids) if current_ids else ""
        
        return vol.Schema({
            vol.Required(CONF_INVERTER_SLAVE_ID, default=inv_ids): str,
        })

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None):
        """Handle reconfiguration of existing inverter and AC charger slave IDs."""
        errors = {}
        
        if user_input is None:
            schema = self._create_reconfigure_schema()
            return self.async_show_form(
                step_id=STEP_RECONFIGURE,
                data_schema=schema
            )
        

        # Simple validation
        inverter_id_str = user_input.get(CONF_INVERTER_SLAVE_ID, "")
        if not inverter_id_str.isdigit():
            errors[CONF_INVERTER_SLAVE_ID] = "invalid_integer_value"
        else:
            inverter_id = int(inverter_id_str)
            if not (1 <= inverter_id <= 246):
                errors[CONF_INVERTER_SLAVE_ID] = "each_id_must_be_between_1_and_246"

        
        if errors:
            schema = self._create_reconfigure_schema(inverter_id_str)
            return self.async_show_form(
                step_id=STEP_RECONFIGURE,
                data_schema=schema, errors=errors
            )

        
        # Update configuration
        new_data = dict(self._data)
        new_data[CONF_INVERTER_SLAVE_ID] = [int(inverter_id_str)]
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)
        return self.async_create_entry(title="", data={})
