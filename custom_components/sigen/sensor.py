"""Sensor platform for Sigenergy ESS integration."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    UnitOfEnergy,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_PLANT,
    DOMAIN,
    RunningState,
)
from .coordinator import SigenergyDataUpdateCoordinator
from .calculated_sensor import SigenergyCalculations as SC, SigenergyCalculatedSensors as SCS, SigenergyIntegrationSensor
from .static_sensor import StaticSensors as SS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sigenergy sensor platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    entities = []
    
    # Get the Home Assistant entity registry
    ha_entity_registry = async_get_entity_registry(hass)
    
    # Create an entity registry to track created entity IDs
    entity_registry = {}  # Format: {(device_type, device_id): {key: entity_id}}
    
    # Helper function to get source entity ID
    def get_source_entity_id(device_type, device_id, source_key):
        """Get the source entity ID for an integration sensor."""
        # First try the exact match from our registry
        device_key = (device_type, device_id)
        if device_key in entity_registry and source_key in entity_registry[device_key]:
            entity_id = entity_registry[device_key][source_key]
            _LOGGER.debug("Found exact match entity %s for key %s", entity_id, source_key)
            return entity_id
        
        # If not found, search for entities that match the pattern
        exact_match_entities = []
        pattern_match_entities = []
        fallback_entities = []
        
        # Normalize device type for matching
        device_type_norm = device_type.lower().replace("_", "")
        
        # Look for entities with various matching patterns
        for entity_id in hass.states.async_entity_ids("sensor"):
            entity_id_lower = entity_id.lower()
            
            # Skip non-sigen entities
            if "sigen" not in entity_id_lower:
                continue
                
            # Exact matches: contains both device type and source key
            if source_key in entity_id_lower and device_type_norm in entity_id_lower:
                exact_match_entities.append(entity_id)
                continue
                
            # Pattern matches: based on device type and key components
            if device_type_norm == "plant" and "plant" in entity_id_lower:
                if "pv" in source_key and "pv" in entity_id_lower and "power" in entity_id_lower:
                    pattern_match_entities.append(entity_id)
                elif "grid" in source_key and "grid" in entity_id_lower:
                    if "import" in source_key and "import" in entity_id_lower:
                        pattern_match_entities.append(entity_id)
                    elif "export" in source_key and "export" in entity_id_lower:
                        pattern_match_entities.append(entity_id)
            elif device_type_norm == "inverter" and "inverter" in entity_id_lower:
                if "pv" in source_key and "pv" in entity_id_lower and "power" in entity_id_lower:
                    pattern_match_entities.append(entity_id)
                    
            # Fallback: any entity containing the source key
            if source_key in entity_id_lower:
                fallback_entities.append(entity_id)
        
        # Use the best match available
        if exact_match_entities:
            _LOGGER.debug(
                "Using exact match entity %s for key %s (device type %s, device ID %s)",
                exact_match_entities[0], source_key, device_type, device_id
            )
            return exact_match_entities[0]
            
        if pattern_match_entities:
            _LOGGER.debug(
                "Using pattern match entity %s for key %s (device type %s, device ID %s)",
                pattern_match_entities[0], source_key, device_type, device_id
            )
            return pattern_match_entities[0]
            
        if fallback_entities:
            _LOGGER.warning(
                "Using fallback entity %s for key %s (device type %s, device ID %s)",
                fallback_entities[0], source_key, device_type, device_id
            )
            return fallback_entities[0]
        
        # Log available entities to help with debugging
        _LOGGER.warning(
            "Could not find source entity with key %s for device type %s, device ID %s",
            source_key, device_type, device_id
        )
        
        # Log all sigen entities to help with debugging
        sigen_entities = [e for e in hass.states.async_entity_ids("sensor") if "sigen" in e.lower()]
        if sigen_entities:
            _LOGGER.debug("Available Sigen sensor entities: %s", sigen_entities)
        else:
            _LOGGER.debug("No Sigen sensor entities found")
        
        return None

    _LOGGER.debug("Setting up sensors for %s", config_entry.data[CONF_NAME])
    _LOGGER.debug("Inverters: %s", coordinator.hub.inverter_slave_ids)
    _LOGGER.debug("config_entry: %s", config_entry)
    _LOGGER.debug("coordinator: %s", coordinator)
    _LOGGER.debug("config_entry.data: %s", config_entry.data)
    _LOGGER.debug("coordinator.hub: %s", coordinator.hub)
    _LOGGER.debug("coordinator.hub.config_entry: %s", coordinator.hub.config_entry)
    _LOGGER.debug("coordinator.hub.config_entry.data: %s", coordinator.hub.config_entry.data)
    _LOGGER.debug("coordinator.hub.config_entry.entry_id: %s", coordinator.hub.config_entry.entry_id)

    # Set plant name
    plant_name : str = config_entry.data[CONF_NAME]

    _LOGGER.debug("Setting up sensors for %s", plant_name)

    # Add plant sensors
    for description in SS.PLANT_SENSORS + SCS.PLANT_SENSORS:
        sensor_name = f"{plant_name} {description.name}"
        entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}"
        _LOGGER.debug("Creating plant sensor with name: %s, expected entity_id: %s, key: %s",
                     sensor_name, entity_id, description.key)
        
        # Track the entity ID
        device_key = (DEVICE_TYPE_PLANT, None)  # Plant has no device_id
        if device_key not in entity_registry:
            entity_registry[device_key] = {}
        entity_registry[device_key][description.key] = entity_id
        
        entities.append(
            SigenergySensor(
                coordinator=coordinator,
                description=description,
                name=sensor_name,
                device_type=DEVICE_TYPE_PLANT,
                device_id=None,
                device_name=plant_name,
            )
        )
    
    # Add plant integration sensors
    for description in SCS.PLANT_INTEGRATION_SENSORS:
        # Look up the source entity ID based on the source key
        source_entity_id = get_source_entity_id(
            DEVICE_TYPE_PLANT,
            None,  # Plant has no device_id
            description.source_key
        )
        
        if source_entity_id:
            _LOGGER.debug("Creating plant integration sensor with source entity ID: %s", source_entity_id)
            entities.append(
                SigenergyIntegrationSensor(
                    coordinator=coordinator,
                    description=description,
                    name=f"{plant_name} {description.name}",
                    device_type=DEVICE_TYPE_PLANT,
                    device_id=None,
                    device_name=plant_name,
                    source_entity_id=source_entity_id,
                    round_digits=description.round_digits,
                    max_sub_interval=description.max_sub_interval,
                )
            )
        else:
            _LOGGER.warning(
                "Skipping integration sensor %s because source entity not found",
                f"{plant_name} {description.name}"
            )

    # Add inverter sensors
    inverter_no = 0
    for inverter_id in coordinator.hub.inverter_slave_ids:
        inverter_name = f"Sigen { f'{plant_name.split()[1] } ' if plant_name.split()[1].isdigit() else ''}Inverter{'' if inverter_no == 0 else f' {inverter_no}'}"
        _LOGGER.debug("Adding inverter %s for plant %s with inverter_no %s as %s", inverter_id, plant_name, inverter_no, inverter_name)
        _LOGGER.debug("Plant name: %s divided by space first part: %s, second part: %s, last part: %s", plant_name, plant_name.split()[0], plant_name.split()[1], plant_name.split()[-1])
        
        # Add inverter sensors
        for description in SS.INVERTER_SENSORS + SCS.INVERTER_SENSORS:
            sensor_name = f"{inverter_name} {description.name}"
            entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}"
            
            # Track the entity ID
            device_key = (DEVICE_TYPE_INVERTER, inverter_id)
            if device_key not in entity_registry:
                entity_registry[device_key] = {}
            entity_registry[device_key][description.key] = entity_id
            
            entities.append(
                SigenergySensor(
                    coordinator=coordinator,
                    description=description,
                    name=sensor_name,
                    device_type=DEVICE_TYPE_INVERTER,
                    device_id=inverter_id,
                    device_name=inverter_name,
                )
            )
            
        # Add inverter integration sensors
        for description in SCS.INVERTER_INTEGRATION_SENSORS:
            # Look up the source entity ID based on the source key
            source_entity_id = get_source_entity_id(
                DEVICE_TYPE_INVERTER,
                inverter_id,
                description.source_key
            )
            
            if source_entity_id:
                _LOGGER.debug("Creating inverter integration sensor with source entity ID: %s", source_entity_id)
                entities.append(
                    SigenergyIntegrationSensor(
                        coordinator=coordinator,
                        description=description,
                        name=f"{inverter_name} {description.name}",
                        device_type=DEVICE_TYPE_INVERTER,
                        device_id=inverter_id,
                        device_name=inverter_name,
                        source_entity_id=source_entity_id,
                        round_digits=description.round_digits,
                        max_sub_interval=description.max_sub_interval,
                    )
                )
            else:
                _LOGGER.warning(
                    "Skipping integration sensor %s because source entity not found",
                    f"{inverter_name} {description.name}"
                )
            
        # Add PV string sensors if we have PV string data
        if coordinator.data and "inverters" in coordinator.data and inverter_id in coordinator.data["inverters"]:
            inverter_data = coordinator.data["inverters"][inverter_id]
            pv_string_count = inverter_data.get("inverter_pv_string_count", 0)
            
            if pv_string_count and isinstance(pv_string_count, (int, float)) and pv_string_count > 0:
                _LOGGER.debug("Adding %d PV string devices for inverter %s with name %s", pv_string_count, inverter_id, inverter_name)
                
                # Create sensors for each PV string
                for pv_idx in range(1, int(pv_string_count) + 1):
                    try:
                        pv_string_name = f"{inverter_name} PV {pv_idx}"
                        pv_string_id = f"{coordinator.hub.config_entry.entry_id}_{str(inverter_name).lower().replace(' ', '_')}_pv{pv_idx}"
                        _LOGGER.debug("Adding PV string %d with name %s and ID %s", pv_idx, pv_string_name, pv_string_id)
                        
                        # Create device info
                        pv_device_info = DeviceInfo(
                            identifiers={(DOMAIN, pv_string_id)},
                            name=pv_string_name,
                            manufacturer="Sigenergy",
                            model="PV String",
                            via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_{str(inverter_name).lower().replace(' ', '_')}"),
                        )
                        
                        # Add sensors for this PV string
                        for description in SS.PV_STRING_SENSORS + SCS.PV_STRING_SENSORS:
                            _LOGGER.debug("Adding sensor %s for PV string %d", description.name, pv_string_name)
                            # Create a copy of the description to add extra parameters
                            if isinstance(description, SC.SigenergySensorEntityDescription):
                                sensor_desc = SC.SigenergySensorEntityDescription.from_entity_description(
                                    description,
                                    extra_params={"pv_idx": pv_idx, "device_id": inverter_id},
                                )
                            else:
                                sensor_desc = description
                            
                            sensor_name = f"{pv_string_name} {description.name}"
                            entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}"
                            
                            # Track the entity ID - use a special key format for PV strings
                            device_key = (DEVICE_TYPE_INVERTER, inverter_id, pv_idx)
                            if device_key not in entity_registry:
                                entity_registry[device_key] = {}
                            entity_registry[device_key][description.key] = entity_id
                                
                            entities.append(
                                PVStringSensor(
                                    coordinator=coordinator,
                                    description=sensor_desc,
                                    name=sensor_name,
                                    device_type=DEVICE_TYPE_INVERTER,  # Use inverter as device type for data access
                                    device_id=inverter_id,
                                    device_name=inverter_name,
                                    device_info=pv_device_info,
                                    pv_string_idx=pv_idx,
                                )
                            )
                            _LOGGER.debug("Added sensor id %s for PV string id %s", sensor_desc.key, pv_string_id)
                    except Exception as ex:
                        _LOGGER.error("Error creating device for PV string %d: %s", pv_idx, ex)
        
        # Increment inverter counter
        inverter_no += 1

    # Add AC charger sensors
    ac_charger_no = 0
    for ac_charger_id in coordinator.hub.ac_charger_slave_ids:
        ac_charger_name=f"Sigen { f'{plant_name.split()[1] } ' if plant_name.split()[1].isdigit() else ''}AC Charger{'' if ac_charger_no == 0 else f' {ac_charger_no}'}"
        _LOGGER.debug("Adding AC charger %s with ac_charger_no %s as %s", ac_charger_id, ac_charger_no, ac_charger_name)
        for description in SS.AC_CHARGER_SENSORS + SCS.AC_CHARGER_SENSORS:
            sensor_name = f"{ac_charger_name} {description.name}"
            entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}"
            
            # Track the entity ID
            device_key = (DEVICE_TYPE_AC_CHARGER, ac_charger_id)
            if device_key not in entity_registry:
                entity_registry[device_key] = {}
            entity_registry[device_key][description.key] = entity_id
            
            entities.append(
                SigenergySensor(
                    coordinator=coordinator,
                    description=description,
                    name=sensor_name,
                    device_type=DEVICE_TYPE_AC_CHARGER,
                    device_id=ac_charger_id,
                    device_name=ac_charger_name,
                )
            )
        ac_charger_no += 1

    # Add DC charger sensors
    dc_charger_no = 0
    for dc_charger_id in coordinator.hub.dc_charger_slave_ids:
        dc_charger_name=f"Sigen { f'{plant_name.split()[1] } ' if plant_name.split()[1].isdigit() else ''}DC Charger{'' if dc_charger_no == 0 else f' {dc_charger_no}'}"
        _LOGGER.debug("Adding DC charger %s with dc_charger_no %s as %s", dc_charger_id, dc_charger_no, dc_charger_name)
        for description in SS.DC_CHARGER_SENSORS + SCS.DC_CHARGER_SENSORS:
            sensor_name = f"{dc_charger_name} {description.name}"
            entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}"
            
            # Track the entity ID
            device_key = (DEVICE_TYPE_DC_CHARGER, dc_charger_id)
            if device_key not in entity_registry:
                entity_registry[device_key] = {}
            entity_registry[device_key][description.key] = entity_id
            
            entities.append(
                SigenergySensor(
                    coordinator=coordinator,
                    description=description,
                    name=sensor_name,
                    device_type=DEVICE_TYPE_DC_CHARGER,
                    device_id=dc_charger_id,
                    device_name=dc_charger_name,
                )
            )
        dc_charger_no += 1

    async_add_entities(entities)

class SigenergySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Sigenergy sensor."""

    entity_description: SC.SigenergySensorEntityDescription

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        description: SensorEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[int],
        device_name: Optional[str] = "",
        device_info: Optional[DeviceInfo] = None,
        pv_string_idx: Optional[int] = None,
    ) -> None:
        """Initialize the sensor."""
        try:

            super().__init__(coordinator)
            self.entity_description = description
            self._attr_name = name
            self._device_type = device_type
            self._device_id = device_id
            self._pv_string_idx = pv_string_idx
            self._device_info_override = device_info

            # Get the device number if any as a string for use in names
            device_number_str = ""
            if device_name:
                parts = device_name.split()
                if parts and parts[-1].isdigit():
                    device_number_str = f" {parts[-1]}"
            # _LOGGER.debug("Device number string for %s: %s", device_name, device_number_str)

            # Set unique ID
            if device_type == DEVICE_TYPE_PLANT:
                self._attr_unique_id = f"{coordinator.hub.config_entry.entry_id}_{device_type}_{description.key}"
                _LOGGER.debug("Unique ID for plant sensor %s", self._attr_unique_id)
            elif device_type == DEVICE_TYPE_INVERTER and pv_string_idx is not None:
                self._attr_unique_id = f"{coordinator.hub.config_entry.entry_id}_{device_type}_{device_number_str}_pv{pv_string_idx}_{description.key}"
                _LOGGER.debug("Unique ID for PV string sensor %s", self._attr_unique_id)
            else:
                self._attr_unique_id = f"{coordinator.hub.config_entry.entry_id}_{device_type}_{device_number_str}_{description.key}"
                _LOGGER.debug("Unique ID for %s sensor %s", device_type, self._attr_unique_id)

            # Set device info (use provided device_info if available)
            if self._device_info_override:
                self._attr_device_info = self._device_info_override
                return
                
            # Otherwise, use default device info logic
            if device_type == DEVICE_TYPE_PLANT:
                self._attr_device_info = DeviceInfo(
                    identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant")},
                    name=device_name,
                    manufacturer="Sigenergy",
                    model="Energy Storage System",
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
            elif device_type == DEVICE_TYPE_DC_CHARGER:
                self._attr_device_info = DeviceInfo(
                    identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_{str(device_name).lower().replace(' ', '_')}")},
                    name=device_name,
                    manufacturer="Sigenergy",
                    model="DC Charger",
                    via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant"),
                )
            else:
                _LOGGER.error("Unknown device type for sensor: %s", device_type)
        except Exception as ex:
            _LOGGER.error("Error initializing SigenergySensor: %s", ex)

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # Special handling for grid import/export power sensors
        if self.entity_description.key in ["plant_grid_import_power", "plant_grid_export_power"]:
            if self.coordinator.data is None or "plant" not in self.coordinator.data:
                _LOGGER.debug("[CS][GridSensor] No coordinator data available for %s", self.entity_id)
                return None
                
            # Call the value_fn directly with the coordinator data
            if hasattr(self.entity_description, "value_fn") and self.entity_description.value_fn is not None:
                try:
                    # Always pass coordinator data to the value_fn
                    transformed_value = self.entity_description.value_fn(
                        None, self.coordinator.data, None
                    )
                    _LOGGER.debug("[CS][GridSensor] Calculated value for %s: %s",
                                 self.entity_id, transformed_value)
                    return transformed_value
                except Exception as ex:
                    _LOGGER.error(
                        "Error applying value_fn for %s: %s",
                        self.entity_id,
                        ex,
                    )
                    return None
        
        # Standard handling for other sensors
        if self.coordinator.data is None:
            return STATE_UNKNOWN
            
        if self._device_type == DEVICE_TYPE_PLANT:
            # Use the key directly with plant_ prefix already included
            value = self.coordinator.data["plant"].get(self.entity_description.key)
        elif self._device_type == DEVICE_TYPE_INVERTER:
            # Use the key directly with inverter_ prefix already included
            value = self.coordinator.data["inverters"].get(self._device_id, {}).get(
                self.entity_description.key
            )
        elif self._device_type == DEVICE_TYPE_AC_CHARGER:
            # Use the key directly with ac_charger_ prefix already included
            value = self.coordinator.data["ac_chargers"].get(self._device_id, {}).get(
                self.entity_description.key
            )
        elif self._device_type == DEVICE_TYPE_DC_CHARGER:
            # Use the key directly with dc_charger_ prefix already included
            value = self.coordinator.data["dc_chargers"].get(self._device_id, {}).get(
                self.entity_description.key
            )
        else:
            value = None

        if value is None or str(value).lower() == "unknown":
            # Always return None for numeric sensors (ones with measurements or units)
            if (self.entity_description.native_unit_of_measurement is not None
                or self.entity_description.state_class in [SensorStateClass.MEASUREMENT, SensorStateClass.TOTAL_INCREASING]):
                return None
            return STATE_UNKNOWN

        # Special handling for timestamp sensors
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            try:
                if not isinstance(value, (int, float)):
                    _LOGGER.warning("Invalid timestamp value type for %s: %s", self.entity_id, type(value))
                    return None
                    
                # Use epoch_to_datetime for timestamp conversion
                converted_timestamp = SC.epoch_to_datetime(value, self.coordinator.data)
                _LOGGER.debug("Timestamp conversion for %s: %s -> %s",
                            self.entity_id, value, converted_timestamp)
                return converted_timestamp
            except Exception as ex:
                _LOGGER.error("Error converting timestamp for %s: %s", self.entity_id, ex)
                return None

        # Apply value_fn if available
        if hasattr(self.entity_description, "value_fn") and self.entity_description.value_fn is not None:
            try:
                # Pass coordinator data if needed by the value_fn
                if hasattr(self.entity_description, "extra_fn_data") and self.entity_description.extra_fn_data:
                    # Pass extra parameters if available
                    extra_params = getattr(self.entity_description, "extra_params", None)
                    transformed_value = self.entity_description.value_fn(value, self.coordinator.data, extra_params)
                else:
                    transformed_value = self.entity_description.value_fn(value)
                    
                if transformed_value is not None:
                    return transformed_value
            except Exception as ex:
                _LOGGER.error(
                    "Error applying value_fn for %s (value: %s, type: %s): %s",
                    self.entity_id,
                    value,
                    type(value),
                    ex,
                )
                return None

        # Special handling for specific keys
        if self.entity_description.key == "plant_on_off_grid_status":
            return {
                0: "On Grid",
                1: "Off Grid (Auto)",
                2: "Off Grid (Manual)",
            }.get(value, STATE_UNKNOWN)
        if self.entity_description.key == "plant_running_state":
            return {
                RunningState.STANDBY: "Standby",
                RunningState.RUNNING: "Running",
                RunningState.FAULT: "Fault",
                RunningState.SHUTDOWN: "Shutdown",
            }.get(value, STATE_UNKNOWN)
        if self.entity_description.key == "inverter_running_state":
            _LOGGER.debug("inverter_running_state value: %s", value)
            return {
                RunningState.STANDBY: "Standby",
                RunningState.RUNNING: "Running",
                RunningState.FAULT: "Fault",
                RunningState.SHUTDOWN: "Shutdown",
            }.get(value, STATE_UNKNOWN)
        if self.entity_description.key == "ac_charger_system_state":
            return {
                0: "System Init",
                1: "A1/A2",
                2: "B1",
                3: "B2",
                4: "C1",
                5: "C2",
                6: "F",
                7: "E",
            }.get(value, STATE_UNKNOWN)
        if self.entity_description.key == "inverter_output_type":
            return {
                0: "L/N",
                1: "L1/L2/L3",
                2: "L1/L2/L3/N",
                3: "L1/L2/N",
            }.get(value, STATE_UNKNOWN)
        if self.entity_description.key == "plant_grid_sensor_status":
            return "Connected" if value == 1 else "Not Connected"

        return value

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        if not self.coordinator.last_update_success:
            return False
            
        if self._device_type == DEVICE_TYPE_PLANT:
            return self.coordinator.data is not None and "plant" in self.coordinator.data
        elif self._device_type == DEVICE_TYPE_INVERTER:
            return (
                self.coordinator.data is not None
                and "inverters" in self.coordinator.data
                and self._device_id in self.coordinator.data["inverters"]
            )
        elif self._device_type == DEVICE_TYPE_AC_CHARGER:
            return (
                self.coordinator.data is not None
                and "ac_chargers" in self.coordinator.data
                and self._device_id in self.coordinator.data["ac_chargers"]
            )
        elif self._device_type == DEVICE_TYPE_DC_CHARGER:
            return (
                self.coordinator.data is not None
                and "dc_chargers" in self.coordinator.data
                and self._device_id in self.coordinator.data["dc_chargers"]
            )
            
        return False


class PVStringSensor(SigenergySensor):
    """Representation of a PV String sensor."""

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        description: SensorEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[int],
        device_name: Optional[str] = "",
        device_info: Optional[DeviceInfo] = None,
        pv_string_idx: Optional[int] = None,
    ) -> None:
        """Initialize the PV string sensor."""
        super().__init__(
            coordinator=coordinator,
            description=description,
            name=name,
            device_type=device_type,
            device_id=device_id,
            device_name=device_name,
            device_info=device_info,
            pv_string_idx=pv_string_idx,
        )

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return STATE_UNKNOWN
            
        try:
            # Get inverter data
            inverter_data = self.coordinator.data["inverters"].get(self._device_id, {})
            if not inverter_data:
                return STATE_UNKNOWN
                
            # Handle different sensor types
            # First check if we have a value_fn (for power and energy sensors)
            if hasattr(self.entity_description, "value_fn") and self.entity_description.value_fn is not None:
                return self.entity_description.value_fn(
                    None,
                    self.coordinator.data,
                    getattr(self.entity_description, "extra_params", {})
                )
            # Then handle other standard sensors
            elif self.entity_description.key == "voltage":
                value = inverter_data.get(f"inverter_pv{self._pv_string_idx}_voltage")
            elif self.entity_description.key == "current":
                value = inverter_data.get(f"inverter_pv{self._pv_string_idx}_current")
            else:
                _LOGGER.debug("Unknown PV string sensor key: %s, returning None", self.entity_description.key)
                return None
                
            if value is None:
                return None
            return value
        except Exception as ex:
            _LOGGER.error("Error getting value for PV string sensor %s: %s", self.entity_id, ex)
            return STATE_UNKNOWN

