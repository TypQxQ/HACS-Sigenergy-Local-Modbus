"""Sensor platform for Sigenergy ESS integration."""

from __future__ import annotations
import logging
from typing import Any, Optional
from decimal import Decimal

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import (  # pylint: disable=syntax-error
    ConfigEntry,
)
from homeassistant.const import (
    CONF_NAME,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SLAVE_ID,
    CONF_INVERTER_HAS_DCCHARGER,
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_PLANT,
    DOMAIN,
    RunningState,
)
from .coordinator import SigenergyDataUpdateCoordinator
from .calculated_sensor import (
    SigenergyCalculations as SC,
    SigenergyCalculatedSensors as SCS,
    SigenergyIntegrationSensor,
)
from .static_sensor import StaticSensors as SS
from .common import *
from .sigen_entity import SigenergyEntity # Import the new base class

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sigenergy sensor platform."""
    coordinator: SigenergyDataUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id]["coordinator"]
    plant_name = config_entry.data[CONF_NAME]

    entities: list[SigenergySensor] = []

    # Add plant sensors
    # Static Sensors:
    async_add_entities(
        generate_sigen_entity(
            plant_name,
            None,
            None,
            coordinator,
            SigenergySensor,
            SS.PLANT_SENSORS,
            DEVICE_TYPE_PLANT,
        )
    )
    # Calculated Sensors:
    async_add_entities(
        generate_sigen_entity(
            plant_name,
            None,
            None,
            coordinator,
            SigenergySensor,
            SCS.PLANT_SENSORS,
            DEVICE_TYPE_PLANT,
        )
    )

    # Calculated Integration Sensors (Plant):
    plant_integration_sensors = generate_sigen_entity(
        plant_name,
        None,
        None,
        coordinator,
        SigenergyIntegrationSensor,
        SCS.PLANT_INTEGRATION_SENSORS,
        DEVICE_TYPE_PLANT,
        hass,
    )
    if plant_integration_sensors:
        async_add_entities(plant_integration_sensors)
        _LOGGER.debug("Registering %d plant integration sensors with coordinator.", len(plant_integration_sensors))
        _LOGGER.debug("The added sensors are: %s", str([s.name for s in plant_integration_sensors]))
        for sensor in plant_integration_sensors:
            if isinstance(sensor, SigenergyIntegrationSensor): # Ensure correct type before appending
                coordinator.integration_sensors.append(sensor)
            else:
                 _LOGGER.warning("generate_sigen_entity returned non-SigenergyIntegrationSensor for plant: %s", type(sensor))

    # Add inverter sensors
    for device_name, device_conn in coordinator.hub.inverter_connections.items():
        # Static Sensors:
        async_add_entities(
            generate_sigen_entity(
                plant_name,
                device_name,
                device_conn,
                coordinator,
                SigenergySensor,
                SS.INVERTER_SENSORS,
                DEVICE_TYPE_INVERTER,
            )
        )
        # Calculated Sensors:
        async_add_entities(
            generate_sigen_entity(
                plant_name,
                device_name,
                device_conn,
                coordinator,
                SigenergySensor,
                SCS.INVERTER_SENSORS,
                DEVICE_TYPE_INVERTER,
            )
        )

        # Calculated Integration Sensors (Inverter):
        inverter_integration_sensors = generate_sigen_entity(
            plant_name,
            device_name,
            device_conn,
            coordinator,
            SigenergyIntegrationSensor,
            SCS.INVERTER_INTEGRATION_SENSORS,
            DEVICE_TYPE_INVERTER,
            hass,
        )
        if inverter_integration_sensors:
            async_add_entities(inverter_integration_sensors)
            _LOGGER.debug("Registering %d inverter integration sensors for '%s' with coordinator.", len(inverter_integration_sensors), device_name)
            _LOGGER.debug("The added sensors are: %s", str([s.name for s in inverter_integration_sensors]))
            for sensor in inverter_integration_sensors:
                 if isinstance(sensor, SigenergyIntegrationSensor): # Ensure correct type
                     coordinator.integration_sensors.append(sensor)
                 else:
                     _LOGGER.warning("generate_sigen_entity returned non-SigenergyIntegrationSensor for inverter '%s': %s", device_name, type(sensor))

        # PV strings
        inverter_data = coordinator.data["inverters"][device_name]
        pv_string_count = inverter_data.get("inverter_pv_string_count", 0)

        if (
            pv_string_count
            and isinstance(pv_string_count, (int, float))
            and pv_string_count > 0
        ):

            # Create sensors for each PV string
            for pv_idx in range(1, int(pv_string_count) + 1):
                try:
                    pv_string_name = f"{device_name} PV{pv_idx}"
                    parent_inverter_id = f"{coordinator.hub.config_entry.entry_id}_{generate_device_id(device_name)}"
                    pv_string_id = f"{parent_inverter_id}_pv{pv_idx}"

                    # Create device info
                    pv_device_info = DeviceInfo(
                        identifiers={(DOMAIN, pv_string_id)},
                        name=pv_string_name,
                        manufacturer="Sigenergy",
                        model="PV String",
                        via_device=(DOMAIN, parent_inverter_id),
                    )

                    # For this PV string add first the static and then the calculated sensors
                    async_add_entities(
                        generate_sigen_entity(
                            plant_name,
                            device_name,
                            device_conn,
                            coordinator,
                            PVStringSensor,
                            SS.PV_STRING_SENSORS,
                            DEVICE_TYPE_INVERTER,
                            hass=hass,
                            device_info=pv_device_info,
                            pv_string_idx=pv_idx,
                        )
                    )

                    async_add_entities(
                        generate_sigen_entity(
                            plant_name,
                            device_name,
                            device_conn,
                            coordinator,
                            PVStringSensor,
                            SCS.PV_STRING_SENSORS,
                            DEVICE_TYPE_INVERTER,
                            hass=hass,
                            device_info=pv_device_info,
                            pv_string_idx=pv_idx,
                        )
                    )

                except Exception as ex:
                    _LOGGER.exception(
                        "Error creating device/sensors for PV string %d: %s", pv_idx, ex
                    )  # Use .exception to include traceback

        # Add DC charger sensors
        if device_conn.get(CONF_INVERTER_HAS_DCCHARGER, False):
            dc_charger_name = f"{device_name} DC Charger"

            dc_name = f"{device_name} DC Charger"
            parent_inverter_id = f"{coordinator.hub.config_entry.entry_id}_{generate_device_id(device_name)}"
            dc_id = f"{parent_inverter_id}_dc_charger"

            # Create device info
            dc_device_info = DeviceInfo(
                identifiers={(DOMAIN, dc_id)},
                name=dc_name,
                manufacturer="Sigenergy",
                model="DC Charger",
                via_device=(DOMAIN, parent_inverter_id),
            )


            # Static Sensors:
            async_add_entities(
                generate_sigen_entity(
                    plant_name,
                    device_name,
                    device_conn,
                    coordinator,
                    SigenergySensor,
                    SS.DC_CHARGER_SENSORS,
                    DEVICE_TYPE_DC_CHARGER,
                    device_info=dc_device_info
                )
            )

    # Add AC charger sensors
    # Iterate through the AC charger connection details dictionary
    for ac_charger_name, ac_details in coordinator.hub.ac_charger_connections.items():
        slave_id = ac_details.get(CONF_SLAVE_ID)
        if slave_id is None:
            _LOGGER.warning(
                "Missing slave ID for AC charger '%s' in configuration, skipping sensor setup.",
                ac_charger_name,
            )
            continue  # Skip this charger if slave_id is missing

        for description in SS.AC_CHARGER_SENSORS + SCS.AC_CHARGER_SENSORS:
            # Use the ac_charger_name directly from the dictionary key
            sensor_name = f"{ac_charger_name} {description.name}"
            # entity_id = f"sensor.{sensor_name.lower().replace(' ', '_')}" # entity_id is usually handled by HA core based on unique_id

            entities.append(
                SigenergySensor(
                    coordinator=coordinator,
                    description=description,
                    name=sensor_name,
                    device_type=DEVICE_TYPE_AC_CHARGER,
                    device_id=str(slave_id),  # Use the retrieved slave_id
                    device_name=ac_charger_name,  # Use the name from the dictionary key
                )
            )

    # Log first 5 entities to see if they look valid
    if entities:  # Only call if list is not empty
        try:
            async_add_entities(entities)
        except Exception as ex:
            _LOGGER.exception(
                "[Setup Entry] Error during final async_add_entities call: %s", ex
            )
    else:
        _LOGGER.debug("[Setup Entry] No entities collected to add.")


class SigenergySensor(SigenergyEntity, SensorEntity):
    """Representation of a Sigenergy sensor."""

    entity_description: SigenergySensorEntityDescription

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        description: SensorEntityDescription | SigenergySensorEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = "",
        device_info: Optional[DeviceInfo] = None,
        pv_string_idx: Optional[int] = None,
    ) -> None:
        """Initialize the sensor."""
        try:
        # Call the base class __init__
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

            # Sensor-specific initialization
            if (
                isinstance(description, SigenergySensorEntityDescription)
                and description.round_digits is not None
            ):
                self._round_digits = description.round_digits
            else:
                self._round_digits = None

        except Exception as ex:
            _LOGGER.exception(
                "[Sensor Init] Error initializing SigenergySensor '%s': %s", name, ex
            )  # Use exception

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.entity_description.key in [
            "plant_grid_import_power",
            "plant_grid_export_power",
            "plant_consumed_power",
        ]:
            if self.coordinator.data is None or "plant" not in self.coordinator.data:
                _LOGGER.warning(
                    "[CS][GridSensor] No coordinator data available for %s",
                    self.entity_id,
                )
                return None

            # Call the value_fn directly with the coordinator data
            if (
                hasattr(self.entity_description, "value_fn")
                and self.entity_description.value_fn is not None
            ):
                try:
                    # Always pass coordinator data to the value_fn
                    transformed_value = self.entity_description.value_fn(
                        None, self.coordinator.data, None
                    )
                    return transformed_value
                except Exception as ex:
                    _LOGGER.error(
                        "Error applying value_fn for %s: %s",
                        self.entity_id,
                        ex,
                    )
                    return None

        if self.coordinator.data is None:
            _LOGGER.error(
                "[CS][native_value] No coordinator data available for %s",
                self.entity_id,
            )
            return STATE_UNKNOWN

        if self._device_type == DEVICE_TYPE_PLANT:
            # Use the key directly with plant_ prefix already included
            value = self.coordinator.data["plant"].get(self.entity_description.key)
        elif self._device_type == DEVICE_TYPE_INVERTER:
            # Use the key directly with inverter_ prefix already included
            # Access inverter data using device_name (inverter_name)
            value = (
                self.coordinator.data.get("inverters", {})
                .get(self._device_name, {})
                .get(self.entity_description.key)
            )
        elif self._device_type == DEVICE_TYPE_AC_CHARGER:
            # Use the key directly with ac_charger_ prefix already included
            # Assuming data is keyed by device_name now, consistent with base class
            value = (
                self.coordinator.data.get("ac_chargers", {})
                #.get(self._device_name, {}) # Use device_name if data is keyed by name
                .get(self._device_id, {})
                .get(self.entity_description.key)
            )
        else:
            value = None

        if value is None or str(value).lower() == "unknown":
            # Always return None for numeric sensors (ones with measurements or units)
            if (
                self.entity_description.native_unit_of_measurement is not None
                or self.entity_description.state_class
                in [SensorStateClass.MEASUREMENT, SensorStateClass.TOTAL_INCREASING]
            ):
                return None
            return STATE_UNKNOWN

        # Special handling for timestamp sensors
        if self.entity_description.device_class == SensorDeviceClass.TIMESTAMP:
            try:
                if not isinstance(value, (int, float)):
                    _LOGGER.warning(
                        "Invalid timestamp value type for %s: %s",
                        self.entity_id,
                        type(value),
                    )
                    return None

                # Use epoch_to_datetime for timestamp conversion
                converted_timestamp = SC.epoch_to_datetime(value, self.coordinator.data)
                return converted_timestamp
            except Exception as ex:
                _LOGGER.error(
                    "Error converting timestamp for %s: %s", self.entity_id, ex
                )
                return None

        # Apply value_fn if available
        if (
            hasattr(self.entity_description, "value_fn")
            and self.entity_description.value_fn is not None
        ):
            try:
                # Pass coordinator data if needed by the value_fn
                if (
                    hasattr(self.entity_description, "extra_fn_data")
                    and self.entity_description.extra_fn_data
                ):
                    # Pass extra parameters if available
                    extra_params = getattr(
                        self.entity_description, "extra_params", None
                    )
                    transformed_value = self.entity_description.value_fn(
                        value, self.coordinator.data, extra_params
                    )
                else:
                    # Pass coordinator data and None for extra_params for consistency
                    transformed_value = self.entity_description.value_fn(
                        value, self.coordinator.data, None
                    )

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

        value = (
            round(value, self._round_digits)
            if isinstance(value, Decimal) and self._round_digits is not None
            else value
        )

        return value

    # The 'available' property is now inherited from SigenergyEntity
    # If specific availability logic is needed for SigenergySensor beyond the base class, uncomment and modify this.


class PVStringSensor(SigenergySensor):
    """Representation of a PV String sensor."""

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        description: SigenergySensorEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[str] = None,
        device_name: Optional[str] = "",
        device_info: Optional[DeviceInfo] = None,
        pv_string_idx: Optional[int] = None,
    ) -> None:

        super().__init__( # Calls SigenergySensor.__init__, which calls SigenergyEntity.__init__
            coordinator=coordinator,
            description=description,
            name=name,
            device_type=device_type,
            device_id=device_id,
            device_name=device_name,
            device_info=device_info,
            pv_string_idx=pv_string_idx,
        )

    # Add this property to PVStringSensor to check its availability based on parent inverter
    @property
    def available(self) -> bool:
        """Return if PV String entity is available based on parent inverter."""
        # Check coordinator status first
        if not self.coordinator.last_update_success:
            _LOGGER.warning(
                "PVStringSensor %s unavailable: Coordinator last update failed.",
                self.entity_id,
            )
            return False
        if not self.coordinator.data or "inverters" not in self.coordinator.data:
            _LOGGER.warning(
                "PVStringSensor %s unavailable: No coordinator data or 'inverters' key.",
                self.entity_id,
            )
            return False

        # Check if the parent inverter data exists using _device_name
        parent_inverter_available = (
            self._device_name in self.coordinator.data["inverters"]
        )

        return parent_inverter_available  # Base availability on parent inverter for now

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            _LOGGER.warning("No coordinator data available for %s", self.entity_id)
            return STATE_UNKNOWN

        try:
            # Access inverter data using device_name (inverter_name)
            inverter_data = self.coordinator.data["inverters"].get(
                self._device_name, {}
            )
            if not inverter_data:
                _LOGGER.warning(
                    "PVStringSensor %s native_value: No inverter data found for '%s'",
                    self.entity_id,
                    self._device_name,
                )
                return STATE_UNKNOWN  # Or None if preferred for numeric sensors

            value = None
            # First check if we have a value_fn (for calculated sensors)
            if (
                hasattr(self.entity_description, "value_fn")
                and self.entity_description.value_fn is not None
            ):
                try:
                    value = self.entity_description.value_fn(
                        None,  # value is not used directly by these functions
                        self.coordinator.data,
                        getattr(self.entity_description, "extra_params", {}),
                    )
                except Exception as fn_ex:
                    _LOGGER.error(
                        "PVStringSensor %s native_value: Error executing value_fn %s: %s",
                        self.entity_id,
                        self.entity_description.value_fn.__name__,
                        fn_ex,
                    )
                    value = None  # Or STATE_UNKNOWN

            else:
                data_key = (
                    f"inverter_pv{self._pv_string_idx}_{self.entity_description.key}"
                )
                value = inverter_data.get(data_key)

            # Final check and return
            if value is None:
                _LOGGER.warning(
                    "PVStringSensor %s native_value: Final value is None, returning None",
                    self.entity_id,
                )
                return None  # Return None for numeric sensors if value is missing

            # Attempt to convert to float if it's numeric, otherwise return as is
            try:
                # Check if it's already a number (int, float, Decimal)
                if isinstance(value, (int, float, Decimal)):
                    return float(value)  # Convert to float for HA consistency
                else:
                    return value  # Return non-numeric values directly
            except (ValueError, TypeError) as conv_ex:
                _LOGGER.warning(
                    "PVStringSensor %s native_value: Could not convert final value '%s' to float: %s",
                    self.entity_id,
                    value,
                    conv_ex,
                )
                return STATE_UNKNOWN  # Or None

        except KeyError as ke:
            _LOGGER.error(
                "PVStringSensor %s native_value: KeyError accessing data: %s",
                self.entity_id,
                ke,
            )
            return STATE_UNKNOWN  # Or None
        except Exception as ex:
            _LOGGER.exception(
                "PVStringSensor %s native_value: Unexpected error getting value: %s",
                self.entity_id,
                ex,
            )
            return STATE_UNKNOWN  # Or None
