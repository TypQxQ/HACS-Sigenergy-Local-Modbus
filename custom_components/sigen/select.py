"""Select platform for Sigenergy ESS integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_PLANT,
    DOMAIN,
    EMSWorkMode,
    RemoteEMSControlMode,
    DEVICE_TYPE_DC_CHARGER,
)
from .coordinator import SigenergyDataUpdateCoordinator
from .modbus import SigenergyModbusError
from .common import *

_LOGGER = logging.getLogger(__name__)

# Map of grid codes to country names
GRID_CODE_MAP = {
    1: "Germany",
    2: "UK",
    3: "Italy",
    4: "Spain",
    5: "Portugal",
    6: "France",
    7: "Poland",
    8: "Hungary",
    9: "Belgium",
    10: "Norway",
    11: "Sweden",
    12: "Finland",
    13: "Denmark",
    # Add more mappings as they are discovered
}

# Reverse mapping for looking up codes by country name
COUNTRY_TO_CODE_MAP = {country: code for code, country in GRID_CODE_MAP.items()}
# Debug log the grid code map
_LOGGER.debug("GRID_CODE_MAP: %s", GRID_CODE_MAP)

def _get_grid_code_display(data, inverter_id):
    """Get the display value for grid code with debug logging."""
    # Log the available inverter data for debugging
    if inverter_id in data.get("inverters", {}):
        _LOGGER.debug("Available inverter data keys: %s", list(data["inverters"][inverter_id].keys()))
    else:
        _LOGGER.debug("No data available for inverter_id %s", inverter_id)
        return "Unknown"
    
    # Get the raw grid code value
    grid_code = data["inverters"].get(inverter_id, {}).get("inverter_grid_code")
    
    # Debug log the value and type
    _LOGGER.debug("Grid code value: %s, type: %s", grid_code, type(grid_code))
    
    # Handle None case
    if grid_code is None:
        return "Unknown"
        
    # Try to convert to int and look up in map
    try:
        grid_code_int = int(grid_code)
        _LOGGER.debug("Converted grid code to int: %s", grid_code_int)
        
        # Look up in map
        result = GRID_CODE_MAP.get(grid_code_int)
        _LOGGER.debug("Grid code map lookup result: %s", result)
        
        if result is not None:
            return result
        else:
            return f"Unknown ({grid_code})"
    except (ValueError, TypeError) as e:
        _LOGGER.debug("Error converting grid code: %s", e)
        return f"Unknown ({grid_code})"



@dataclass
class SigenergySelectEntityDescription(SelectEntityDescription):
    """Class describing Sigenergy select entities."""

    current_option_fn: Callable[[Dict[str, Any], Optional[int]], str] = None
    select_option_fn: Callable[[Any, Optional[int], str], None] = None
    available_fn: Callable[[Dict[str, Any], Optional[int]], bool] = lambda data, _: True
    entity_registry_enabled_default: bool = True


PLANT_SELECTS = [
    SigenergySelectEntityDescription(
        key="plant_remote_ems_control_mode",
        name="Remote EMS Control Mode",
        icon="mdi:remote",
        options=[
            "PCS Remote Control",
            "Standby",
            "Maximum Self Consumption",
            "Command Charging (Grid First)",
            "Command Charging (PV First)",
            "Command Discharging (PV First)",
            "Command Discharging (ESS First)",
        ],
        current_option_fn=lambda data, _: {
            RemoteEMSControlMode.PCS_REMOTE_CONTROL: "PCS Remote Control",
            RemoteEMSControlMode.STANDBY: "Standby",
            RemoteEMSControlMode.MAXIMUM_SELF_CONSUMPTION: "Maximum Self Consumption",
            RemoteEMSControlMode.COMMAND_CHARGING_GRID_FIRST: "Command Charging (Grid First)",
            RemoteEMSControlMode.COMMAND_CHARGING_PV_FIRST: "Command Charging (PV First)",
            RemoteEMSControlMode.COMMAND_DISCHARGING_PV_FIRST: "Command Discharging (PV First)",
            RemoteEMSControlMode.COMMAND_DISCHARGING_ESS_FIRST: "Command Discharging (ESS First)",
        }.get(data["plant"].get("plant_remote_ems_control_mode"), "Unknown"),
        select_option_fn=lambda hub, _, option: hub.async_write_plant_parameter(
            "plant_remote_ems_control_mode",
            {
                "PCS Remote Control": RemoteEMSControlMode.PCS_REMOTE_CONTROL,
                "Standby": RemoteEMSControlMode.STANDBY,
                "Maximum Self Consumption": RemoteEMSControlMode.MAXIMUM_SELF_CONSUMPTION,
                "Command Charging (Grid First)": RemoteEMSControlMode.COMMAND_CHARGING_GRID_FIRST,
                "Command Charging (PV First)": RemoteEMSControlMode.COMMAND_CHARGING_PV_FIRST,
                "Command Discharging (PV First)": RemoteEMSControlMode.COMMAND_DISCHARGING_PV_FIRST,
                "Command Discharging (ESS First)": RemoteEMSControlMode.COMMAND_DISCHARGING_ESS_FIRST,
            }.get(option, RemoteEMSControlMode.PCS_REMOTE_CONTROL),
        ),
        available_fn=lambda data, _: data["plant"].get("plant_remote_ems_enable") == 1,
    ),
]

INVERTER_SELECTS = [
    SigenergySelectEntityDescription(
        key="inverter_grid_code",
        name="Grid Code",
        icon="mdi:transmission-tower",
        options=list(GRID_CODE_MAP.values()),
        entity_category=EntityCategory.CONFIG,
        current_option_fn=lambda data, inverter_id: (
            # Define a simple function to get grid code with debug logging
            _get_grid_code_display(data, inverter_id)
        ),
        select_option_fn=lambda hub, inverter_id, option: hub.async_write_inverter_parameter(
            inverter_id,
            "inverter_grid_code",
            COUNTRY_TO_CODE_MAP.get(option, 0)  # Default to 0 if country not found
        ),
    ),
]

AC_CHARGER_SELECTS = []
DC_CHARGER_SELECTS = []

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sigenergy select platform."""
    coordinator: SigenergyDataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    plant_name = config_entry.data[CONF_NAME]
    _LOGGER.debug(f"Starting to add {SigenergySelect}")
    # Add plant Switches
    entities : list[SigenergySelect] = generate_sigen_entity(plant_name, None, None, coordinator, SigenergySelect,
                                           PLANT_SELECTS, DEVICE_TYPE_PLANT)

    # Add inverter Selects
    for device_name, device_conn in coordinator.hub.inverter_connections.items():
        entities += generate_sigen_entity(plant_name, device_name, device_conn, coordinator, SigenergySelect,
                                           INVERTER_SELECTS, DEVICE_TYPE_INVERTER)

    # Add AC charger Switches
    for device_name, device_conn in coordinator.hub.ac_charger_connections.items():
        entities += generate_sigen_entity(plant_name, device_name, device_conn, coordinator, SigenergySelect,
                                           AC_CHARGER_SELECTS, DEVICE_TYPE_AC_CHARGER)

    # Add DC charger Switches
    for device_name, device_conn in coordinator.hub.dc_charger_connections.items():
        entities += generate_sigen_entity(plant_name, device_name, device_conn, coordinator, SigenergySelect,
                                           DC_CHARGER_SELECTS, DEVICE_TYPE_DC_CHARGER)
        
    _LOGGER.debug(f"Class to add {SigenergySelect}")
    async_add_entities(entities)
    return

class SigenergySelect(CoordinatorEntity, SelectEntity):
    """Representation of a Sigenergy select."""

    entity_description: SigenergySelectEntityDescription

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        description: SigenergySelectEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[int],
        device_name: Optional[str] = "",
        pv_string_idx: Optional[int] = None,
    ) -> None:
        """Initialize the select."""
        super().__init__(coordinator)
        self.entity_description = description
        self.hub = coordinator.hub
        self._attr_name = name
        self._device_type = device_type
        self._device_id = device_id
        self._attr_options = description.options
        self._pv_string_idx = pv_string_idx
        
        # Get the device number if any as a string for use in names
        device_number_str = device_name.split()[-1]
        device_number_str = f" {device_number_str}" if device_number_str.isdigit() else ""

        # Set unique ID
        self._attr_unique_id = generate_unique_entity_id(device_type, device_name, coordinator, description.key, pv_string_idx)
        
        # Set device info
        if device_type == DEVICE_TYPE_PLANT:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant")},
                name=device_name,
                manufacturer="Sigenergy",
                model="Energy Storage System",
                # via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant"),
            )
        elif device_type == DEVICE_TYPE_INVERTER:
            # Get model and serial number if available
            model = None
            serial_number = None
            sw_version = None
            if coordinator.data and "inverters" in coordinator.data:
                inverter_data = coordinator.data["inverters"].get(device_id, {})
                model = inverter_data.get("inverter_model_type")
                serial_number = inverter_data.get("inverter_serial_number")
                sw_version = inverter_data.get("inverter_machine_firmware_version")

            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_{str(device_name).lower().replace(' ', '_')}")},
                name=device_name,
                manufacturer="Sigenergy",
                model=model,
                serial_number=serial_number,
                sw_version=sw_version,
                via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant"),
            )
        elif device_type == DEVICE_TYPE_AC_CHARGER:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_{str(device_name).lower().replace(' ', '_')}")},
                name=device_name,
                manufacturer="Sigenergy",
                model="AC Charger",
                via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant"),
            )

    @property
    def current_option(self) -> str:
        """Return the selected entity option."""
        if self.coordinator.data is None:
            return self.options[0] if self.options else ""
            
        return self.entity_description.current_option_fn(self.coordinator.data, self._device_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        if self._device_type == DEVICE_TYPE_PLANT:
            if not (self.coordinator.data is not None and "plant" in self.coordinator.data):
                return False
                
            # Check if the entity has a specific availability function
            if hasattr(self.entity_description, "available_fn"):
                return self.entity_description.available_fn(self.coordinator.data, self._device_id)
                
            return True
        elif self._device_type == DEVICE_TYPE_INVERTER:
            if not (
                self.coordinator.data is not None
                and "inverters" in self.coordinator.data
                and self._device_id in self.coordinator.data["inverters"]
            ):
                return False
                
            # Check if the entity has a specific availability function
            if hasattr(self.entity_description, "available_fn"):
                return self.entity_description.available_fn(self.coordinator.data, self._device_id)
                
            return True
        elif self._device_type == DEVICE_TYPE_AC_CHARGER:
            if not (
                self.coordinator.data is not None
                and "ac_chargers" in self.coordinator.data
                and self._device_id in self.coordinator.data["ac_chargers"]
            ):
                return False
                
            # Check if the entity has a specific availability function
            if hasattr(self.entity_description, "available_fn"):
                return self.entity_description.available_fn(self.coordinator.data, self._device_id)
                
            return True
            
        return False

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            await self.entity_description.select_option_fn(self.hub, self._device_id, option)
            await self.coordinator.async_request_refresh()
        except SigenergyModbusError as error:
            _LOGGER.error("Failed to select option %s for %s: %s", option, self.name, error)