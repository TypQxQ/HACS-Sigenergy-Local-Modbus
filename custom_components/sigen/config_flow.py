"""Config flow for Sigenergy ESS integration."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
import asyncio
import re
import logging
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ConnectionException, ModbusException

import voluptuous as vol

from homeassistant import (
    config_entries,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.config_entries import (  # pylint: disable=syntax-error
    ConfigFlowResult,
)
from homeassistant.helpers.device_registry import (
    async_get as async_get_device_registry,
    async_entries_for_config_entry,  # Import the helper function
)
from homeassistant.helpers.entity_registry import (
    async_get as async_get_entity_registry,
    async_entries_for_device,
)
from .modbus import _suppress_pymodbus_logging
from .const import *

_LOGGER = logging.getLogger(__name__)

DEFAULT_PLANT_CONNECTION = {
                CONF_HOST: "",
                CONF_PORT: DEFAULT_PORT,
                CONF_INVERTER_SLAVE_ID: DEFAULT_INVERTER_SLAVE_ID,
                CONF_SCAN_INTERVAL_HIGH: DEFAULT_SCAN_INTERVAL_HIGH,
                CONF_SCAN_INTERVAL_ALARM: DEFAULT_SCAN_INTERVAL_ALARM, 
                CONF_SCAN_INTERVAL_MEDIUM: DEFAULT_SCAN_INTERVAL_MEDIUM,
                CONF_SCAN_INTERVAL_LOW: DEFAULT_SCAN_INTERVAL_LOW,
}

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

def generate_plant_schema(
        user_input,
        discovered_ip = "",
        migration_alternative = False,
        use_inverter_device_id = False,
        reset_state_alternative = False,
        display_update_frq = False
    ) -> vol.Schema:
    """Dynamically create schema using the determined prefill_host

    Args:
        user_input (_type_, optional): _description_. Defaults to None.
        discovered_ip (str, optional): _description_. Defaults to "".
        migration_alternative (bool, optional): _description_. Defaults to False.
        reset_state_alternative (bool, optional): _description_. Defaults to False.

    Returns:
        vol.Schema: _description_
    """
    slave_id_type = CONF_INVERTER_SLAVE_ID if use_inverter_device_id else CONF_SLAVE_ID

    validation_schema = {
                vol.Required(CONF_HOST, default = user_input[CONF_HOST] or discovered_ip): str,
                vol.Required(CONF_PORT, default = user_input[CONF_PORT]): int
    }

    _LOGGER.debug("slave_id_type: %s",slave_id_type)
    validation_schema[vol.Required(slave_id_type, default=user_input[slave_id_type])] = int
    validation_schema[vol.Required(CONF_READ_ONLY,
                                   default=user_input.get(CONF_READ_ONLY, DEFAULT_READ_ONLY))] = bool

    if migration_alternative:
        validation_schema[vol.Required(CONF_MIGRATE_YAML,
                                       default=user_input.get(CONF_MIGRATE_YAML, False))] = bool
    elif reset_state_alternative:
        validation_schema[vol.Required(CONF_RESET_VALUES,
                                       default=user_input.get(CONF_RESET_VALUES, False))] = bool

    if display_update_frq:
        validation_schema[vol.Required(CONF_SCAN_INTERVAL_HIGH,
                                       default=user_input.get(CONF_SCAN_INTERVAL_HIGH,DEFAULT_SCAN_INTERVAL_HIGH))] = vol.All(vol.Coerce(int))
        validation_schema[vol.Required(CONF_SCAN_INTERVAL_ALARM,
                                       default=user_input.get(CONF_SCAN_INTERVAL_ALARM,DEFAULT_SCAN_INTERVAL_ALARM))] = vol.All(vol.Coerce(int))
        validation_schema[vol.Required(CONF_SCAN_INTERVAL_MEDIUM,
                                       default=user_input.get(CONF_SCAN_INTERVAL_MEDIUM, DEFAULT_SCAN_INTERVAL_MEDIUM))] = vol.All(vol.Coerce(int))
        validation_schema[vol.Required(CONF_SCAN_INTERVAL_LOW,
                                       default=user_input.get(CONF_SCAN_INTERVAL_LOW, DEFAULT_SCAN_INTERVAL_LOW))] = vol.All(vol.Coerce(int))

    schema = vol.Schema(validation_schema)
    return schema

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

    if not port or not 1 <= port <= 65535:
        errors["port"] = "invalid_port"

    return errors


def validate_slave_id(slave_id: int, field_name: str = CONF_SLAVE_ID) -> Dict[str, str]:
    """Validate a slave ID."""
    errors = {}

    if slave_id is None or not 1 <= slave_id <= 246:
        errors[field_name] = "each_id_must_be_between_1_and_246"

    return errors


def get_highest_device_number(names: List[str]) -> int:
    """Get the highest numbered device from a list of device names.
    This function extracts the numeric part from each device name in the list,
    and returns the highest number found. If no numbers are found in any name,
    or if the list is empty, returns 0.
    Args:
        names: A list of device name strings, potentially containing numbers
    Returns:
        int: The highest device number found, or 0 if no numbered devices exist
    """
    if not names or len(names) < 1:
        return 0

    def extract_number(name):
        if not name:
            return 0
        match = re.search(r"\d+", name)
        return int(match.group()) if match else 0

    name = max(names, key=extract_number, default="")
    match = re.search(r"\d+", name)
    return int(match.group()) if match else 1


@config_entries.HANDLERS.register(DOMAIN)
class SigenergyConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for Sigenergy ESS."""

    VERSION = 2
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data = {}
        self._plants = {}
        self._inverters = {}
        self._devices = {}
        self._selected_plant_entry_id = None
        self._discovered_ip = None
        self._discovered_device_type = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step when adding a new device."""
        _LOGGER.debug("Starting config initiated by user.")
        # Load existing plants
        await self._async_load_plants()

        # If no plants exist, go directly to plant configuration
        if not self._plants:
            self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_NEW_PLANT
            return await self.async_step_plant_config()

        # Otherwise, show device type selection
        return await self.async_step_device_type()

    async def async_step_dhcp(self, discovery_info) -> ConfigFlowResult:
        """Handle DHCP discovery."""

        # Store the discovered IP
        self._discovered_ip = discovery_info.ip
        _LOGGER.debug("Starting config for DHCP discovered with ip: %s", self._discovered_ip)
        self.context["title_placeholders"] = {"name": str(discovery_info.ip)}

        # Set unique ID based on discovery info to allow ignoring/updates
        unique_id = f"dhcp_{self._discovered_ip}"
        await self.async_set_unique_id(unique_id)
        # Abort if this discovery (IP) is already configured OR ignored
        self._abort_if_unique_id_configured(updates={CONF_HOST: self._discovered_ip})

        device_type = await self.async_check_device_type(
            self._discovered_ip, DEFAULT_PORT, DEFAULT_INVERTER_SLAVE_ID)

        self._discovered_device_type = device_type
        if device_type == DEVICE_TYPE_DC_CHARGER:
            name = f"Inverter + DC ({str(discovery_info.ip)})"
        elif device_type == DEVICE_TYPE_INVERTER:
            name = "Inverter"
        elif device_type == DEVICE_TYPE_AC_CHARGER:
            name = "AC Charger"
        else:
            name = "Unknown"

        self.context["title_placeholders"] = {"name": name}
        _LOGGER.debug("[async_step_dhcp] Device Type %s for %s", device_type, name)

        await self._async_load_plants()

        # If no plants exist, configure as new plant (and primary inverter)
        if not self._plants:
            self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_NEW_PLANT
            # Unique ID for the discovery was set above.
            return await self.async_step_plant_config()

        # Check if this IP is already configured in any *active* config entry
        # This prevents offering configuration for an already integrated device part
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            if entry.source == config_entries.SOURCE_IGNORE:
                continue # Skip ignored entries

            # Check Plant connection
            plant_conn = entry.data.get(CONF_PLANT_CONNECTION, {})
            if plant_conn.get(CONF_HOST) == self._discovered_ip:
                _LOGGER.info(
                    "DHCP discovered IP %s matches existing plant %s. Aborting.",
                    self._discovered_ip, entry.title
                )
                return self.async_abort(reason="already_configured_device") # Use generic reason

            # Check Inverter connections
            inverter_conns = entry.data.get(CONF_INVERTER_CONNECTIONS, {})
            for inv_name, inv_details in inverter_conns.items():
                if inv_details.get(CONF_HOST) == self._discovered_ip:
                    _LOGGER.info(
                        "DHCP discovered IP %s matches existing inverter %s in plant %s. Aborting.",
                        self._discovered_ip, inv_name, entry.title
                    )
                    return self.async_abort(reason="already_configured_device") # Use generic reason

            # Check AC Charger connections
            ac_charger_conns = entry.data.get(CONF_AC_CHARGER_CONNECTIONS, {})
            for ac_name, ac_details in ac_charger_conns.items():
                if ac_details.get(CONF_HOST) == self._discovered_ip:
                    _LOGGER.info(
                        "DHCP discovered IP %s matches existing AC charger %s in %s. Aborting.",
                        self._discovered_ip, ac_name, entry.title
                    )
                    return self.async_abort(reason="already_configured_device") # Use generic reason

        # Otherwise, let user choose configuration type
        return await self.async_step_dhcp_select_plant()

    async def async_step_dhcp_select_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle selection between new plant or adding to existing plant."""
        if user_input is None:
            options = {
                DEVICE_TYPE_NEW_PLANT: "Configure as New Plant",
                DEVICE_TYPE_INVERTER: "Add as Inverter to Existing Plant",
                DEVICE_TYPE_AC_CHARGER: "Add as AC Charger to Existing Plant",}
            return self.async_show_form(
                step_id=STEP_DHCP_SELECT_PLANT,
                data_schema=vol.Schema({
                    # Changed key to 'action' to reflect broader choices
                    vol.Required("action"): vol.In(options)
                }),
                description_placeholders={"ip_address": self._discovered_ip or "unknown"},
                # last_step=False # Indicate this isn't necessarily the final step
            )

        # Use 'action' key instead of 'device_type'
        selected_action = user_input["action"]

        # Existing logic for new plant or adding inverter or AC charger
        self._data[CONF_DEVICE_TYPE] = selected_action # Store the selected device type

        if selected_action == DEVICE_TYPE_NEW_PLANT:
            # Unique ID for the discovery was set in async_step_dhcp.
            # We might need a different unique ID if creating a full plant entry.
            # Let's reset it here to be specific to the plant being created.
            await self.async_set_unique_id(f"plant_{self._discovered_ip}", raise_on_progress=False)
            self._abort_if_unique_id_configured(updates={CONF_HOST: self._discovered_ip})
            return await self.async_step_plant_config()
        # Assuming DEVICE_TYPE_INVERTER or DEVICE_TYPE_AC_CHARGER 
        # are the only other non-ignore options here
        else:
            # Ensure plants are loaded if we jump directly here via DHCP with existing plants
            if not self._plants:
                await self._async_load_plants()
            # No unique ID needed here as we are adding to an existing plant entry
            return await self.async_step_select_plant()


    async def async_step_device_type(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
        elif device_type in [
            DEVICE_TYPE_INVERTER,
            DEVICE_TYPE_AC_CHARGER,
            DEVICE_TYPE_DC_CHARGER,
        ]:
            return await self.async_step_select_plant()

        # Should never reach here
        return self.async_abort(reason="unknown_device_type")

    async def async_step_plant_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the plant configuration step when adding a new plant device."""

        errors = {}
        has_dc_charger = False

        # Check if the accumulated energy consumption sensor exists
        legacy_yaml_present = self.hass.states.get(next(iter(LEGACY_SENSOR_MIGRATION_MAP.values())))
        if legacy_yaml_present:
            _LOGGER.debug(
            "Found old yaml integration."
            )
            # Store or use accumulatedEnergyState.state if needed for setup logic
        else:
            _LOGGER.debug("Old yaml integration does not exist.")


        if user_input is None:
            schema = generate_plant_schema(DEFAULT_PLANT_CONNECTION,
                                           discovered_ip=self._discovered_ip or "",
                                           migration_alternative=bool(legacy_yaml_present),
                                           use_inverter_device_id=True
            )

            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=schema,
            )

        # Process and validate inverter ID
        try:
            inverter_id = int(user_input[CONF_INVERTER_SLAVE_ID])
            if not 1 <= inverter_id <= 246:
                errors[CONF_INVERTER_SLAVE_ID] = "each_id_must_be_between_1_and_246"
        except (ValueError, TypeError):
            errors[CONF_INVERTER_SLAVE_ID] = "invalid_integer_value"

        if not errors:
            device_type = await self.async_check_device_type(user_input[CONF_HOST],
                                                        user_input[CONF_PORT],
                                                        user_input[CONF_INVERTER_SLAVE_ID])
            if device_type == DEVICE_TYPE_DC_CHARGER:
                has_dc_charger = True
            elif device_type == DEVICE_TYPE_INVERTER:
                has_dc_charger = False
            else:
                errors[CONF_HOST] = "Couldn't connect."

            _LOGGER.debug("errors is: %s , %s", str(True if errors else False), errors)

        if errors:
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=generate_plant_schema(user_input,
                                                  discovered_ip=self._discovered_ip or "",
                                                  migration_alternative=bool(legacy_yaml_present),
                                                  use_inverter_device_id=True
                                                  ),
                                            errors=errors,
            )

        # Create the plant connection dictionary
        new_plant_connection = DEFAULT_PLANT_CONNECTION
        new_plant_connection[CONF_HOST] = user_input[CONF_HOST]
        new_plant_connection[CONF_PORT] = user_input[CONF_PORT]
        self._data[CONF_PLANT_CONNECTION] = new_plant_connection

        # Create the inverter connections dictionary for the implicit first inverter
        inverter_name = "Sigen Inverter"
        self._data[CONF_INVERTER_CONNECTIONS] = {
            inverter_name: {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: inverter_id,
                CONF_INVERTER_HAS_DCCHARGER: has_dc_charger,
            }
        }

        # Store the plant name generated based on the number of installed plants
        plant_no = get_highest_device_number(list(self._plants.keys()))

        self._data[CONF_NAME] = (
            f"Sigen Plant{'' if plant_no == 0 else f' {plant_no + 1}'}"
        )

        # Set the device type as plant
        self._data[CONF_DEVICE_TYPE] = DEVICE_TYPE_PLANT

        # If chose to migrate, save sensor values to migrate to.
        values_to_initialize = {}
        if user_input.get(CONF_MIGRATE_YAML, False):
            _LOGGER.debug("Migration option True")
            for new_sensor, old_sensor in LEGACY_SENSOR_MIGRATION_MAP.items():
                value = self.hass.states.get(old_sensor)
                if value:
                    _LOGGER.debug("Adding migrating values %s for %s", value.state, new_sensor)
                    values_to_initialize[new_sensor] = str(value.state)

        # Save choice if to migrate data at first run after plant being added.
        self._data[CONF_VALUES_TO_INIT] = values_to_initialize
        _LOGGER.debug("Values to migrate: %s", values_to_initialize)

        # Create the configuration entry with the default name
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    async def async_test_connection(self, host, port, slave_id, register_address,
                                    register_count=1, timeout=1) -> dict[str, str]:
        errors = {}
        # Check the connection
        _LOGGER.debug("DHCP discovery: Testing Modbus connection to %s:%s", host, port)
        response = await self.async_check_device_type(host, port, slave_id, timeout)
        if response not in [DEVICE_TYPE_UNKNOWN, DEVICE_TYPE_INVERTER, 
                               DEVICE_TYPE_DC_CHARGER, DEVICE_TYPE_AC_CHARGER]:
            errors[CONF_HOST] = response
        return errors

    async def _async_try_read_register(self, client: AsyncModbusTcpClient, host: str, port: int, slave_id: int, register_address: int) -> str:
        """Helper to attempt reading a single Modbus register."""
        try:
            result = await client.read_input_registers(
                address=register_address,
                count=1,
                slave=slave_id
            )
            if result and not result.isError():
                _LOGGER.debug("Modbus read successful for register %s on %s:%s, slave %s.",
                              register_address, host, port, slave_id)
                return ""
            else:
                err = f"Modbus read failed or returned error for register " +\
                    f"{register_address} on {host}:{port}, slave {slave_id}."
                _LOGGER.debug(err)
                return err
        except (ModbusException, asyncio.TimeoutError) as e:
            err = "Modbus exception during read for register %s on %s: %s" % \
                (register_address, host, e)
            _LOGGER.debug(err)
            return err
        except Exception as e:
            err = "Unexpected error during Modbus read for register %s on %s: %s" % \
                (register_address, host, e)
            _LOGGER.warning(err)
            return err

    async def async_check_device_type(self, host, port, slave_id, timeout=1) -> str:
        """Check the device type by attempting to read specific Modbus registers."""
        # Define checks: (Device Type Constant, Register Address)
        # Order matters: Check DC Charger first as it's part of the inverter.
        device_checks = [
            (DEVICE_TYPE_DC_CHARGER, 31501),  # dc_charger_charging_current (inverter *with* DC)
            (DEVICE_TYPE_INVERTER, 30578),    # inverter_running_state (inverter *without* DC)
            (DEVICE_TYPE_AC_CHARGER, 32000),  # ac_charger_system_state
        ]

        err = None
        found_device_type = DEVICE_TYPE_UNKNOWN
        client = AsyncModbusTcpClient(host=host, port=port, timeout=timeout)

        try:
            with _suppress_pymodbus_logging():
                if not await client.connect():
                    _LOGGER.debug("Modbus connection failed to %s:%s", host, port)
                    return DEVICE_TYPE_UNKNOWN # Cannot determine type if connection fails

                _LOGGER.debug("Modbus connected to %s:%s. Checking device type...", host, port)

                for device_type, register_address in device_checks:
                    # Returns error message if failed.
                    if not await self._async_try_read_register(
                        client, host, port, slave_id, register_address):
                    # Special case: If DC Charger register read succeeds, it's an Inverter *with* DC.
                    # The loop structure handles this implicitly by checking DC first.
                    # If the DC check passes, we return DEVICE_TYPE_DC_CHARGER.
                    # If it fails, the next iteration checks the standard inverter register.
                        found_device_type = device_type
                        _LOGGER.debug("Identified as %s based on register %s", device_type, register_address)
                        err = None # Clear any previous error
                        break # Stop checking once a type is identified
                    else:
                         err = f"Check failed for {device_type} (register {register_address})"
                         _LOGGER.debug(err)


        except (ConnectionException, asyncio.TimeoutError) as e:
            err = f"Modbus connection failed for {host}: {e}"
            _LOGGER.debug(err)
        except Exception as e:
            err = f"Unexpected error during device type check for {host}: {e}"
            _LOGGER.warning(err)
        finally:
            if client:
                client.close()
                _LOGGER.debug("Modbus test client closed for %s.", host)

        _LOGGER.debug("Final identified type for %s:%s (Slave %s): %s", 
                      host, port, slave_id, found_device_type)
        return found_device_type if not err else err

    async def async_step_select_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the plant selection step when adding a new child device."""
        if not self._plants:
            # No plants available, abort with error
            return self.async_abort(reason="no_plants_available")

        if user_input is None:
            # Create schema with plant selection
            schema = vol.Schema(
                {vol.Required(CONF_PARENT_PLANT_ID): vol.In(self._plants)}
            )

            return self.async_show_form(
                step_id=STEP_SELECT_PLANT,
                data_schema=schema,
            )

        # Store the selected plant ID
        self._selected_plant_entry_id = user_input[CONF_PARENT_PLANT_ID]
        self._data[CONF_PARENT_PLANT_ID] = self._selected_plant_entry_id

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
    ) -> ConfigFlowResult:
        """Handle the inverter configuration step when adding a new inverter device."""
        errors = {}

        # Dynamically create schema to pre-fill host if discovered via DHCP
        schema = vol.Schema({
            vol.Required(CONF_HOST, default=self._discovered_ip or ""): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_SLAVE_ID, default=DEFAULT_INVERTER_SLAVE_ID): int,
            })

        if user_input is None:
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
            )

        # Check connection
        try:
            inverter_id = int(user_input[CONF_SLAVE_ID])
            if not 1 <= inverter_id <= 246:
                errors[CONF_SLAVE_ID] = "each_id_must_be_between_1_and_246"
        except (ValueError, TypeError):
            errors[CONF_SLAVE_ID] = "invalid_integer_value"

        errors.update(await self.async_test_connection(user_input[CONF_HOST],
                                                       user_input[CONF_PORT],
                                                       user_input[CONF_SLAVE_ID],
                                                       30578))  # inverter_running_state

        if not errors:
            dc_charger_error = {}
            dc_charger_error.update(await self.async_test_connection(user_input[CONF_HOST],
                                                        user_input[CONF_PORT],
                                                        user_input[CONF_SLAVE_ID],
                                                        31501))  # dc_charger_charging_current
            if not dc_charger_error:
                _LOGGER.debug("DC charger connection successful for %s", user_input[CONF_HOST])

        if errors:
            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
                errors=errors,
            )


        assert self._selected_plant_entry_id is not None  # Ensure ID is set before use
        plant_entry = self.hass.config_entries.async_get_entry(
            self._selected_plant_entry_id
        )
        if plant_entry:
            _LOGGER.debug("Selected plant entry ID: %s", self._selected_plant_entry_id)
            _LOGGER.debug("Plant entry data: %s", plant_entry.data)
            # Check against existing inverter slave IDs in the connections dictionary
            inverter_connections = plant_entry.data.get(CONF_INVERTER_CONNECTIONS, {})
            # _LOGGER.debug("Existing inverter connections: %s", inverter_connections)

            # Get the inverter name based on number of existing inverters
            inverter_no = get_highest_device_number(list(inverter_connections.keys()))
            inverter_name = (
                f"Sigen Inverter{'' if inverter_no == 0 else f' {inverter_no + 1}'}"
            )
            # _LOGGER.debug("InverterName generated: %s", inverter_name)

            # Create the new connection
            new_inverter_connection = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: user_input[CONF_SLAVE_ID],
                CONF_INVERTER_HAS_DCCHARGER: not dc_charger_error,
            }

            # Create or update the inverter connections dictionary
            new_data = dict(plant_entry.data)
            inverter_connections[inverter_name] = new_inverter_connection
            _LOGGER.debug("Updated inverter connections: %s", inverter_connections)

            # Update the plant's configuration with the new inverter
            new_data[CONF_INVERTER_CONNECTIONS] = inverter_connections
            _LOGGER.debug("New data for plant entry: %s", new_data)

            # Update the plant's configuration with the new inverter
            self.hass.config_entries.async_update_entry(plant_entry, data=new_data)
            self.hass.config_entries._async_schedule_save()
            # Reload the entry to ensure changes take effect
            await self.hass.config_entries.async_reload(plant_entry.entry_id)

            return self.async_abort(reason="device_added")

        return self.async_abort(reason="parent_plant_not_found")

    async def async_step_ac_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the AC charger configuration step when adding a new AC charger device."""
        errors = {}

        def get_schema(data_source: Dict):
            return vol.Schema({
                vol.Required(CONF_HOST, default=data_source.get(CONF_HOST, "")): str,
                vol.Required(CONF_PORT, default=data_source.get(CONF_PORT, DEFAULT_PORT)): int,
                vol.Required(CONF_SLAVE_ID, default=data_source.get(CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID)): int,
                })

        if user_input is None:
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=get_schema({}),
            )

        # Validate the slave ID
        slave_id = user_input.get(CONF_SLAVE_ID)
        if slave_id is None or not 1 <= slave_id <= 246:
            errors[CONF_SLAVE_ID] = "each_id_must_be_between_1_and_246"
            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=get_schema(user_input),
                errors=errors,
            )

        # Check for duplicate IDs and conflicts with inverters
        assert self._selected_plant_entry_id is not None  # Ensure ID is set before use
        plant_entry = self.hass.config_entries.async_get_entry(
            self._selected_plant_entry_id
        )
        if plant_entry:
            # Get existing AC charger connections dictionary
            ac_charger_connections = plant_entry.data.get(
                CONF_AC_CHARGER_CONNECTIONS, {}
            )

            # Check connection if not already errors
            if not errors:
                errors.update(await self.async_test_connection(user_input[CONF_HOST],
                                                            user_input[CONF_PORT],
                                                            user_input[CONF_SLAVE_ID],
                                                            32000))  # ac_charger_system_state

            if errors:
                return self.async_show_form(
                    step_id=STEP_AC_CHARGER_CONFIG,
                    data_schema=get_schema(user_input),
                    errors=errors,
                )

            # Get the AC charger name based on number of existing AC chargers
            ac_charger_no = get_highest_device_number(
                list(ac_charger_connections.keys())
            )

            # Get the number if any from the last ac_charger if any.
            ac_charger_name = (
                f"Sigen AC Charger{'' if ac_charger_no == 0 else f' {ac_charger_no + 1}'}"
            )

            # Create or update the AC charger connections dictionary
            new_data = dict(plant_entry.data)
            ac_charger_connections = new_data.get(CONF_AC_CHARGER_CONNECTIONS, {})
            ac_charger_connections[ac_charger_name] = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: slave_id,
            }

            # Update the plant's configuration with the new AC charger
            new_data[CONF_AC_CHARGER_CONNECTIONS] = ac_charger_connections

            self.hass.config_entries.async_update_entry(plant_entry, data=new_data)

            # Save configuration to file
            self.hass.config_entries._async_schedule_save()

            # Reload the entry to ensure changes take effect
            await self.hass.config_entries.async_reload(plant_entry.entry_id)

            return self.async_abort(reason="device_added")

        return self.async_abort(reason="parent_plant_not_found")

    async def async_step_select_inverter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the inverter selection step when adding a new DC charger device."""

        # Get the plant data
        assert self._selected_plant_entry_id is not None  # Ensure ID is set before use
        plant_entry = self.hass.config_entries.async_get_entry(
            self._selected_plant_entry_id
        )
        if not plant_entry:
            return self.async_abort(reason="parent_plant_not_found")

        # Get the inverter connections without a DC Charger
        inverter_connections_without_dc = {
            name: details
            for name, details in plant_entry.data.get(
                CONF_INVERTER_CONNECTIONS, {}
            ).items()
            if not details.get(CONF_INVERTER_HAS_DCCHARGER, False)
        }
        _LOGGER.debug("Inverter connections: %s", inverter_connections_without_dc)

        inverters_without_dc = self._get_inverters_to_display(
            inverter_connections_without_dc
        )

        if not inverters_without_dc:
            # No inverters available, abort with error
            return self.async_abort(reason="no_inverters_available")

        if user_input is None:
            # Create schema with inverter selection
            schema = vol.Schema(
                {vol.Required(CONF_PARENT_INVERTER_ID): vol.In(inverters_without_dc)}
            )

            return self.async_show_form(
                step_id=STEP_SELECT_INVERTER,
                data_schema=schema,
            )

        # Get the selected inverter connection details
        selected_inverter = user_input[CONF_PARENT_INVERTER_ID]
        _LOGGER.debug("Selected inverter: %s", selected_inverter)

        selected_inverter_name = selected_inverter.split(" (Host:")[0]
        inverter_details = inverter_connections_without_dc[selected_inverter_name]
        inverter_name = selected_inverter_name
        _LOGGER.debug(
            "Selected inverter: %s, details: %s", inverter_name, inverter_details
        )

        # Create the new connection
        new_inverter_connection = {
            CONF_HOST: inverter_details[CONF_HOST],
            CONF_PORT: inverter_details[CONF_PORT],
            CONF_SLAVE_ID: inverter_details[CONF_SLAVE_ID],
            CONF_INVERTER_HAS_DCCHARGER: True,
        }

        # Create or update the inverter connections dictionary
        new_data = dict(plant_entry.data)
        inverter_connections = new_data.get(CONF_INVERTER_CONNECTIONS, {})
        inverter_connections[inverter_name] = new_inverter_connection
        _LOGGER.debug("Updated inverter connections: %s", inverter_connections)

        # Update the plant's configuration with the new inverter
        new_data[CONF_INVERTER_CONNECTIONS] = inverter_connections
        _LOGGER.debug("New data for plant entry: %s", new_data)

        # Update the plant's configuration with the new inverter
        self.hass.config_entries.async_update_entry(plant_entry, data=new_data)
        self.hass.config_entries._async_schedule_save()
        # Reload the entry to ensure changes take effect
        await self.hass.config_entries.async_reload(plant_entry.entry_id)

        return self.async_abort(reason="device_added")

    async def _async_load_plants(self) -> None:
        """Load existing plants from config entries when adding a new device."""
        self._plants = {}

        # Log the number of config entries for debugging
        _LOGGER.debug(
            "Total config entries: %s",
            len(self.hass.config_entries.async_entries(DOMAIN)),
        )

        for entry in self.hass.config_entries.async_entries(DOMAIN):
            # Log each entry to see what's being found
            _LOGGER.debug(
                "Found entry: %s, device type: %s",
                entry.entry_id,
                entry.data.get(CONF_DEVICE_TYPE),
            )

            if entry.data.get(CONF_DEVICE_TYPE) == DEVICE_TYPE_PLANT:
                self._plants[entry.entry_id] = entry.data.get(
                    CONF_NAME, f"Plant {entry.entry_id}"
                )

        # Log the plants that were found
        _LOGGER.debug("Found plants: %s", self._plants)

    async def _async_load_inverters(self, plant_entry_id: str) -> None:
        """Load existing inverters for a specific plant when adding a new DC charger device."""
        self._inverters = {}

        plant_entry = self.hass.config_entries.async_get_entry(plant_entry_id)
        if not plant_entry:
            _LOGGER.error(
                "SigenergyConfigFlow.async_load_inverters: No plant entry found for ID: %s",
                plant_entry_id,
            )
            return
        plant_data = dict(plant_entry.data)
        inverter_connections = plant_data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug("Inverter connections: %s", inverter_connections)

        self._inverters = self._get_inverters_to_display(inverter_connections)
        _LOGGER.debug(
            "Found inverters for plant %s: %s", plant_entry_id, self._inverters
        )

    def _get_inverters_to_display(
        self,
        inverter_connections: Dict[str, Dict],
        with_dc: Optional[bool] = True,
        without_dc: Optional[bool] = True,
    ) -> List[str]:
        """Retrieve inverters for a specific plant."""

        inverters = []

        for inv_name, inv_details in inverter_connections.items():
            has_dc = inv_details.get(CONF_DC_CHARGER_CONNECTIONS, False)
            _LOGGER.debug("Processing inverter: %s, has DC: %s", inv_name, has_dc)
            if not without_dc and not has_dc:
                continue
            if not with_dc and has_dc:
                continue
            display_name = f"{inv_name} (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"
            inverters.append(
                display_name
            )  # Changed from inverters[i] to inverters.append

        return inverters

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
            plant_host = self._data.get(CONF_PLANT_CONNECTION, {}).get(CONF_HOST, "")

            # Add the plant itself with host info
            self._devices[f"plant_{plant_entry_id}"] = (
                f"{plant_name} (Host: {plant_host})"
            )

            # Add inverters
            inverter_connections = self._data.get(CONF_INVERTER_CONNECTIONS, {})

            # Process inverters
            for inv_name, inv_details in inverter_connections.items():
                device_key = f"inverter_{inv_name}"

                display_name = f"{inv_name} (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"

                self._devices[device_key] = display_name

            # Add AC chargers with host info
            ac_charger_connections = self._data.get(CONF_AC_CHARGER_CONNECTIONS, {})

            for ac_name, ac_details in ac_charger_connections.items():
                device_key = f"ac_{ac_name}"

                display_name = f"{ac_name} (Host: {ac_details.get(CONF_HOST)}, ID: {ac_details.get(CONF_SLAVE_ID)})"

                self._devices[device_key] = display_name

            # Add DC chargers
            for inv_name, inv_details in inverter_connections.items():
                if not inv_details.get(CONF_INVERTER_HAS_DCCHARGER, False):
                    continue

                device_key = f"dc_{inv_name}"
                display_name = f"{inv_name} DC Charger (Host: {inv_details.get(CONF_HOST)}, ID: {inv_details.get(CONF_SLAVE_ID)})"

                self._devices[device_key] = display_name

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
            schema = vol.Schema(
                {vol.Required("selected_device"): vol.In(self._devices)}
            )

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
        self._selected_device = {"type": device_type, "id": device_id}
        _LOGGER.debug("Parsed selected device: %s", self._selected_device)

        # Store the selected device for later use
        self._temp_config["selected_device"] = self._selected_device

        # Route to the appropriate configuration step
        if device_type == "plant":
            return await self.async_step_plant_config()
        elif device_type == "inverter":
            return await self.async_step_inverter_config()
        elif device_type == "ac":
            return await self.async_step_ac_charger_config()
        elif device_type == "dc":
            return await self.async_step_dc_charger_config()

        # Fallback
        return self.async_abort(reason=f"unknown_device_type: {device_type}")

    async def async_step_plant_config(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle reconfiguration of an existing plant device."""
        errors = {}

        if user_input is None:
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=generate_plant_schema(self._data[CONF_PLANT_CONNECTION],
                                                  reset_state_alternative= True,
                                                  display_update_frq=True
                                                  )
            )

        # Validate host and port
        host_port_errors = validate_host_port(
            user_input.get(CONF_HOST, ""), user_input.get(CONF_PORT, 0)
        )
        errors.update(host_port_errors)


        _LOGGER.debug("Read user_input: %s", user_input)


        # Validate scan intervals
        high_interval = user_input.get(CONF_SCAN_INTERVAL_HIGH, DEFAULT_SCAN_INTERVAL_HIGH)
        medium_interval = user_input.get(CONF_SCAN_INTERVAL_MEDIUM, DEFAULT_SCAN_INTERVAL_MEDIUM)
        low_interval = user_input.get(CONF_SCAN_INTERVAL_LOW, DEFAULT_SCAN_INTERVAL_LOW)
        alarm_interval = user_input.get(CONF_SCAN_INTERVAL_ALARM, DEFAULT_SCAN_INTERVAL_ALARM)

        if high_interval < 1:
            errors[CONF_SCAN_INTERVAL_HIGH] = "must_be_at_least_1"

        # Validate divisibility
        for interval in [CONF_SCAN_INTERVAL_MEDIUM, CONF_SCAN_INTERVAL_LOW, CONF_SCAN_INTERVAL_ALARM]:
            if high_interval > 0 and user_input[interval] % high_interval != 0:
                errors[interval] = "must_be_divisible_by_high"

        # Validate Medium Interval
        if not errors.get(CONF_SCAN_INTERVAL_MEDIUM) and medium_interval < high_interval:
            errors[CONF_SCAN_INTERVAL_MEDIUM] = "cannot_be_lower_than_high"

        # Validate Low Interval
        if not errors.get(CONF_SCAN_INTERVAL_LOW) and low_interval < medium_interval:
            errors[CONF_SCAN_INTERVAL_LOW] = "cannot_be_lower_than_medium"

        # Validate Alarm Interval
        if not errors.get(CONF_SCAN_INTERVAL_ALARM) and alarm_interval < high_interval:
            errors[CONF_SCAN_INTERVAL_ALARM] = "cannot_be_lower_than_high"

        if errors:
            # Re-create schema with user input values for error display
            return self.async_show_form(
                step_id=STEP_PLANT_CONFIG,
                data_schema=generate_plant_schema(user_input,
                                                  reset_state_alternative= True,
                                                  display_update_frq=True
                                                  ),
                errors=errors
            )

        # Update the configuration entry data (only host, port, read_only)
        new_data = dict(self._data) # Start with existing data
        new_data[CONF_PLANT_CONNECTION][CONF_HOST] = user_input[CONF_HOST]
        new_data[CONF_PLANT_CONNECTION][CONF_PORT] = user_input[CONF_PORT]
        new_data[CONF_PLANT_CONNECTION][CONF_READ_ONLY] = user_input[CONF_READ_ONLY]
        new_data[CONF_PLANT_CONNECTION][CONF_SCAN_INTERVAL_HIGH] = high_interval
        new_data[CONF_PLANT_CONNECTION][CONF_SCAN_INTERVAL_ALARM] = alarm_interval
        new_data[CONF_PLANT_CONNECTION][CONF_SCAN_INTERVAL_MEDIUM] = medium_interval
        new_data[CONF_PLANT_CONNECTION][CONF_SCAN_INTERVAL_LOW] = low_interval

        _LOGGER.debug("Update intervals:")
        _LOGGER.debug(f"High: {high_interval}, Medium: {medium_interval}, Low: {low_interval}, Alarm: {alarm_interval}")
        

        # If chose to reset values, save sensor values to reset.
        values_to_initialize = {}
        if user_input[CONF_RESET_VALUES]:
            _LOGGER.debug("Reseting option True")
            for new_sensor in LEGACY_SENSOR_MIGRATION_MAP.keys():
                _LOGGER.debug("Adding 0 as init value for %s", new_sensor)
                values_to_initialize[new_sensor] = "0"

        # Save choice if to migrate data at first run after plant being added.
        new_data[CONF_VALUES_TO_INIT] = values_to_initialize
        _LOGGER.debug("Values to init as 0: %s", values_to_initialize)

        # Update data if changed (optional check, keeping existing behavior for now)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # Save configuration to file
        self.hass.config_entries._async_schedule_save()

        # Reload the entry to ensure changes take effect
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return self.async_create_entry(title="Sigenergy", data={})

    async def async_step_inverter_config(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguration of an existing inverter device."""
        errors = {}

        # Get the inverter details
        inverter_name = self._selected_device["id"] if self._selected_device else None
        inverter_connections = self._data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug(
            "Inverter name: %s, connections: %s", inverter_name, inverter_connections
        )
        inverter_details = inverter_connections.get(inverter_name, {})

        if user_input is None:
            # Create schema with previously saved values
            schema = vol.Schema(
                {
                    vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
                    vol.Required(
                        CONF_HOST, default=inverter_details.get(CONF_HOST, "")
                    ): str,
                    vol.Required(
                        CONF_PORT, default=inverter_details.get(CONF_PORT, DEFAULT_PORT)
                    ): int,
                    vol.Required(
                        CONF_SLAVE_ID,
                        default=inverter_details.get(
                            CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID
                        ),
                    ): int,
                }
            )

            return self.async_show_form(
                step_id=STEP_INVERTER_CONFIG,
                data_schema=schema,
            )

        # Create schema with current values that we can return on errors.
        schema = vol.Schema(
            {
                vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
                vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)
                ): int,
                vol.Required(
                    CONF_SLAVE_ID,
                    default=user_input.get(CONF_SLAVE_ID, DEFAULT_INVERTER_SLAVE_ID),
                ): int,
            }
        )

        # Check if user wants to remove the device
        if user_input.get(CONF_REMOVE_DEVICE, False):
            # Get configuration data to change
            new_data = dict(self._data)

            # Remove from inverter connections
            new_inverter_connections = dict(inverter_connections)
            if inverter_name in new_inverter_connections:
                del new_inverter_connections[inverter_name]

        # Else if we update the info
        else:
            # Validate host, port, and slave ID
            host_port = user_input.get(CONF_PORT, "")
            host_port_errors = validate_host_port(
                host_port, user_input.get(CONF_PORT, 0)
            )
            errors.update(host_port_errors)

            # Validate slave ID
            slave_id = user_input.get(CONF_SLAVE_ID)
            errors.update(validate_slave_id(slave_id or 0) or {})

            if errors:
                return self.async_show_form(
                    step_id=STEP_INVERTER_CONFIG,
                    data_schema=schema,
                    errors=errors,
                )

            # Create the new inverter details
            new_connection = {
                CONF_HOST: user_input.get(CONF_HOST),
                CONF_PORT: host_port,
                CONF_SLAVE_ID: slave_id,
                CONF_INVERTER_HAS_DCCHARGER: inverter_details.get(
                    CONF_INVERTER_HAS_DCCHARGER, False
                ),
            }

            # If the inverter connections have changed
            if new_connection != inverter_details:
                # Update the inverter configuration
                new_inverter_connections = dict(inverter_connections)
                new_inverter_connections[inverter_name] = new_connection

        ### End if

        # Update the configuration entry with the new connections
        new_data = dict(self._data)
        new_data[CONF_INVERTER_CONNECTIONS] = new_inverter_connections

        # Update the configuration entry (Ensure correct arguments and remove duplicate)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # Wipe all old entities and devices
        _LOGGER.debug(
            "Inverter config updated (removed), removing existing devices/entities before reload."
        )
        await self._async_remove_devices_and_entities(inverter_name)

        # Save configuration to file
        self.hass.config_entries._async_schedule_save()

        # Reload the entry to ensure changes take effect
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return self.async_create_entry(title="Sigenergy", data={})

    async def async_step_ac_charger_config(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration of an existing AC charger device."""
        errors = {}

        # Get the AC charger details
        ac_charger_name: Optional[str] = (
            self._selected_device["id"] if self._selected_device else None
        )
        ac_charger_connections = self._data.get(CONF_AC_CHARGER_CONNECTIONS, {})
        ac_charger_details = ac_charger_connections.get(ac_charger_name, {})

        if user_input is None:
            # Create schema with current values
            schema = vol.Schema(
                {
                    vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
                    vol.Required(
                        CONF_HOST, default=ac_charger_details.get(CONF_HOST, "")
                    ): str,
                    vol.Required(
                        CONF_PORT,
                        default=ac_charger_details.get(CONF_PORT, DEFAULT_PORT),
                    ): int,
                    vol.Required(
                        CONF_SLAVE_ID, default=ac_charger_details.get(CONF_SLAVE_ID, 1)
                    ): int,
                }
            )

            return self.async_show_form(
                step_id=STEP_AC_CHARGER_CONFIG,
                data_schema=schema,
            )

        # Re-create schema with user input values for error display
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_REMOVE_DEVICE,
                    default=user_input.get(CONF_REMOVE_DEVICE, False),
                ): bool,
                vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "")): str,
                vol.Required(
                    CONF_PORT, default=user_input.get(CONF_PORT, DEFAULT_PORT)
                ): int,
                vol.Required(
                    CONF_SLAVE_ID, default=user_input.get(CONF_SLAVE_ID, 1)
                ): int,
            }
        )

        # Check if user wants to remove the device
        if user_input.get(CONF_REMOVE_DEVICE, False):
            # Remove the AC charger
            new_data = dict(self._data)

            # Remove from AC charger connections
            new_ac_charger_connections = dict(ac_charger_connections)
            if ac_charger_name in new_ac_charger_connections:
                del new_ac_charger_connections[ac_charger_name]

        # Else if we update the info
        else:
            # Validate host, port, and slave ID
            host_port = user_input.get(CONF_PORT, "")
            host_port_errors = validate_host_port(
                host_port, user_input.get(CONF_PORT, 0)
            )
            errors.update(host_port_errors)

            # Validate slave ID
            slave_id = user_input.get(CONF_SLAVE_ID)
            errors.update(validate_slave_id(slave_id or 0) or {})

            if errors:
                return self.async_show_form(
                    step_id=STEP_AC_CHARGER_CONFIG,
                    data_schema=schema,
                    errors=errors,
                )

            # Create the new inverter details
            new_connection = {
                CONF_HOST: user_input[CONF_HOST],
                CONF_PORT: user_input[CONF_PORT],
                CONF_SLAVE_ID: slave_id,
            }

            # If the AC Charger connection has changed
            if new_connection != ac_charger_details:
                new_ac_charger_connections = dict(ac_charger_connections)
                new_ac_charger_connections[ac_charger_name] = new_connection

        # Update the AC charger configuration
        new_data = dict(self._data)
        new_data[CONF_AC_CHARGER_CONNECTIONS] = new_ac_charger_connections

        # Update the configuration entry (Ensure correct arguments and remove duplicate)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

        # Wipe all old entities and devices
        await self._async_remove_devices_and_entities(ac_charger_name)

        # Save configuration to file
        self.hass.config_entries._async_schedule_save()

        # Reload the entry to ensure changes take effect
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)

        return self.async_create_entry(title="Sigenergy", data={})

    async def async_step_dc_charger_config(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle reconfiguration of an existing DC charger device."""
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Optional(CONF_REMOVE_DEVICE, default=False): bool,
                }
            )

            return self.async_show_form(
                step_id=STEP_DC_CHARGER_CONFIG,
                data_schema=schema,
            )

        if user_input.get(CONF_REMOVE_DEVICE, False):
            plant_entry = self
            inverter_name: str = (
                self._selected_device.get("id", "") if self._selected_device else ""
            )
            inverter_connections = plant_entry._data.get(CONF_INVERTER_CONNECTIONS, {})
            _LOGGER.debug("Inverter connections: %s", inverter_connections)
            inverter_details = inverter_connections[inverter_name]

            new_inverter_connection = {
                CONF_HOST: inverter_details[CONF_HOST],
                CONF_PORT: inverter_details[CONF_PORT],
                CONF_SLAVE_ID: inverter_details[CONF_SLAVE_ID],
                CONF_INVERTER_HAS_DCCHARGER: False,
            }

            # Create or update the inverter connections dictionary
            new_data = dict(plant_entry._data)
            inverter_connections = new_data.get(CONF_INVERTER_CONNECTIONS, {})
            inverter_connections[inverter_name] = new_inverter_connection
            _LOGGER.debug("Updated inverter connections: %s", inverter_connections)

            # Update the plant's configuration with the new inverter
            new_data[CONF_INVERTER_CONNECTIONS] = inverter_connections
            _LOGGER.debug("New data for plant entry: %s", new_data)

            # Update the plant's configuration with the new inverter
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

            # Wipe all old entities and devices
            _LOGGER.debug(
                "Inverter config updated (removed), removing existing devices/entities before reload."
            )
            await self._async_remove_devices_and_entities(f"{inverter_name} DC Charger")

            # Save configuration to file
            self.hass.config_entries._async_schedule_save()

            # Reload the entry to ensure changes take effect
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="Sigenergy", data={})

        # Handle non-removal case (no changes, but still cleanup before returning)
        _LOGGER.debug(
            "DC charger config step finished without removal, cleaning up before returning."
        )

        return self.async_create_entry(
            title="", data={}
        )  # Existing return for non-removal

    async def _async_remove_devices_and_entities(
        self, device_name: str | None = None
    ) -> None:
        """Remove all devices and entities associated with this config entry."""
        device_registry = async_get_device_registry(self.hass)
        entity_registry = async_get_entity_registry(self.hass)

        _LOGGER.info(
            "Removing all devices and entities for config entry %s prior to reload",
            self.config_entry.entry_id,
        )
        devices_in_config = async_entries_for_config_entry(
            device_registry, self.config_entry.entry_id
        )

        if not devices_in_config:
            _LOGGER.debug(
                "No devices found for config entry %s to remove.",
                self.config_entry.entry_id,
            )
            return

        _LOGGER.debug("Found total of %d devices.", len(devices_in_config))

        for device_entry in devices_in_config:
            if (
                device_name
                and device_entry.name
                and not device_entry.name.startswith(device_name)
            ):
                continue
            entity_entries = async_entries_for_device(
                entity_registry, device_entry.id, include_disabled_entities=True
            )
            _LOGGER.debug(
                "Found %d entities for device %s (%s, %s) to remove.",
                len(entity_entries),
                device_entry.id,
                device_entry.name_by_user or "",
                device_entry.name or "",
            )
            for entity_entry in entity_entries:
                _LOGGER.debug("Removing entity: %s", entity_entry.entity_id)
                entity_registry.async_remove(entity_entry.entity_id)

            _LOGGER.debug("Removing device: %s", device_entry.id)
            device_registry.async_remove_device(device_entry.id)

        _LOGGER.info(
            "Finished removing devices and entities for config entry %s.",
            self.config_entry.entry_id,
        )
