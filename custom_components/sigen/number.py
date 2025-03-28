"""Number platform for Sigenergy ESS integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_NAME,
    EntityCategory,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_SLAVE_ID, # Import CONF_SLAVE_ID
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_PLANT,
    DOMAIN,
)
from .coordinator import SigenergyDataUpdateCoordinator
from .modbus import SigenergyModbusError

_LOGGER = logging.getLogger(__name__)


@dataclass
class SigenergyNumberEntityDescription(NumberEntityDescription):
    """Class describing Sigenergy number entities."""

    # Provide default lambdas instead of None to satisfy type checker
    value_fn: Callable[[Dict[str, Any], Optional[int]], float] = lambda data, id: 0.0
    set_value_fn: Callable[[Any, Optional[int], float], None] = lambda hub, id, value: None
    available_fn: Callable[[Dict[str, Any], Optional[int]], bool] = lambda data, _: True
    entity_registry_enabled_default: bool = True


PLANT_NUMBERS = [
    SigenergyNumberEntityDescription(
        key="plant_active_power_fixed_target",
        name="Active Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_active_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_active_power_fixed_target", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_reactive_power_fixed_target",
        name="Reactive Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement="kVar",
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_reactive_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_reactive_power_fixed_target", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_active_power_percentage_target",
        name="Active Power Percentage Adjustment",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_active_power_percentage_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_active_power_percentage_target", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_qs_ratio_target",
        name="Q/S Adjustment",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-60,
        native_max_value=60,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_qs_ratio_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_qs_ratio_target", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_power_factor_target",
        name="Power Factor Adjustment",
        icon="mdi:sine-wave",
        native_min_value=-1,
        native_max_value=1,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_power_factor_target", 0) / 1000,
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_power_factor_target", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_ess_max_charging_limit",
        name="ESS Max Charging Limit",
        icon="mdi:battery-charging",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_ess_max_charging_limit", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_ess_max_charging_limit", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_ess_max_discharging_limit",
        name="ESS Max Discharging Limit",
        icon="mdi:battery-charging-outline",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_ess_max_discharging_limit", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_ess_max_discharging_limit", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_pv_max_power_limit",
        name="PV Max Power Limit",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_pv_max_power_limit", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_pv_max_power_limit", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_grid_point_maximum_export_limitation",
        name="Grid Export Limitation",
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_grid_point_maximum_export_limitation", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_grid_point_maximum_export_limitation", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_grid_maximum_import_limitation",
        name="Grid Import Limitation",
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_grid_maximum_import_limitation", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_grid_maximum_import_limitation", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_pcs_maximum_export_limitation",
        name="PCS Export Limitation",
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_pcs_maximum_export_limitation", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_pcs_maximum_export_limitation", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_pcs_maximum_import_limitation",
        name="PCS Import Limitation",
        icon="mdi:transmission-tower-import",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=0,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_pcs_maximum_import_limitation", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_pcs_maximum_import_limitation", value),
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_a_active_power_fixed_target",
        name="Phase A Active Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_a_active_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_a_active_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_b_active_power_fixed_target",
        name="Phase B Active Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_b_active_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_b_active_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_c_active_power_fixed_target",
        name="Phase C Active Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_c_active_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_c_active_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_a_reactive_power_fixed_target",
        name="Phase A Reactive Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement="kVar",
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_a_reactive_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_a_reactive_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_b_reactive_power_fixed_target",
        name="Phase B Reactive Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement="kVar",
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_b_reactive_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_b_reactive_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_c_reactive_power_fixed_target",
        name="Phase C Reactive Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement="kVar",
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_c_reactive_power_fixed_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_c_reactive_power_fixed_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_a_active_power_percentage_target",
        name="Phase A Active Power Percentage",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_a_active_power_percentage_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_a_active_power_percentage_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_b_active_power_percentage_target",
        name="Phase B Active Power Percentage",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_b_active_power_percentage_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_b_active_power_percentage_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_c_active_power_percentage_target",
        name="Phase C Active Power Percentage",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_c_active_power_percentage_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_c_active_power_percentage_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_a_qs_ratio_target",
        name="Phase A Q/S Ratio",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-60,
        native_max_value=60,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_a_qs_ratio_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_a_qs_ratio_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_b_qs_ratio_target",
        name="Phase B Q/S Ratio",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-60,
        native_max_value=60,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_b_qs_ratio_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_b_qs_ratio_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
    SigenergyNumberEntityDescription(
        key="plant_phase_c_qs_ratio_target",
        name="Phase C Q/S Ratio",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-60,
        native_max_value=60,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, _: data["plant"].get("plant_phase_c_qs_ratio_target", 0),
        set_value_fn=lambda hub, _, value: hub.async_write_plant_parameter("plant_phase_c_qs_ratio_target", value),
        available_fn=lambda data, _: data["plant"].get("plant_independent_phase_power_control_enable") == 1,
    ),
]

INVERTER_NUMBERS = [
    SigenergyNumberEntityDescription(
        key="inverter_active_power_fixed_adjustment",
        name="Active Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, inverter_id: data["inverters"].get(inverter_id, {}).get("inverter_active_power_fixed_adjustment", 0),
        set_value_fn=lambda hub, inverter_id, value: hub.async_write_inverter_parameter(inverter_id, "inverter_active_power_fixed_adjustment", value),
    ),
    SigenergyNumberEntityDescription(
        key="inverter_reactive_power_fixed_adjustment",
        name="Reactive Power Fixed Adjustment",
        icon="mdi:flash",
        native_unit_of_measurement="kVar",
        native_min_value=-100,
        native_max_value=100,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, inverter_id: data["inverters"].get(inverter_id, {}).get("inverter_reactive_power_fixed_adjustment", 0),
        set_value_fn=lambda hub, inverter_id, value: hub.async_write_inverter_parameter(inverter_id, "inverter_reactive_power_fixed_adjustment", value),
    ),
    SigenergyNumberEntityDescription(
        key="inverter_active_power_percentage_adjustment",
        name="Active Power Percentage Adjustment",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-100,
        native_max_value=100,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, inverter_id: data["inverters"].get(inverter_id, {}).get("inverter_active_power_percentage_adjustment", 0),
        set_value_fn=lambda hub, inverter_id, value: hub.async_write_inverter_parameter(inverter_id, "inverter_active_power_percentage_adjustment", value),
    ),
    SigenergyNumberEntityDescription(
        key="inverter_reactive_power_qs_adjustment",
        name="Reactive Power Q/S Adjustment",
        icon="mdi:percent",
        native_unit_of_measurement=PERCENTAGE,
        native_min_value=-60,
        native_max_value=60,
        native_step=0.01,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, inverter_id: data["inverters"].get(inverter_id, {}).get("inverter_reactive_power_qs_adjustment", 0),
        set_value_fn=lambda hub, inverter_id, value: hub.async_write_inverter_parameter(inverter_id, "inverter_reactive_power_qs_adjustment", value),
    ),
    SigenergyNumberEntityDescription(
        key="inverter_power_factor_adjustment",
        name="Power Factor Adjustment",
        icon="mdi:sine-wave",
        native_min_value=-1,
        native_max_value=1,
        native_step=0.001,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, inverter_id: data["inverters"].get(inverter_id, {}).get("inverter_power_factor_adjustment", 0) / 1000,
        set_value_fn=lambda hub, inverter_id, value: hub.async_write_inverter_parameter(inverter_id, "inverter_power_factor_adjustment", value),
    ),
]
AC_CHARGER_NUMBERS = [
    SigenergyNumberEntityDescription(
        key="ac_charger_output_current",
        name="Charger Output Current",
        icon="mdi:current-ac",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        native_min_value=6,
        native_max_value=32,  # This will be adjusted dynamically based on rated current
        native_step=1,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda data, ac_charger_id: data["ac_chargers"].get(ac_charger_id, {}).get("ac_charger_output_current", 0),
        set_value_fn=lambda hub, ac_charger_id, value: hub.async_write_ac_charger_parameter(ac_charger_id, "ac_charger_output_current", value),
    ),
]

DC_CHARGER_NUMBERS = []



async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Sigenergy number platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    hub = hass.data[DOMAIN][config_entry.entry_id]["hub"]
    entities = []

    # Add plant numbers
    plant_name = config_entry.data[CONF_NAME]
    for description in PLANT_NUMBERS:
        entities.append(
            SigenergyNumber(
                coordinator=coordinator,
                hub=hub,
                description=description,
                name=f"{plant_name} {description.name}",
                device_type=DEVICE_TYPE_PLANT,
                device_id=None,
                device_name=plant_name,
            )
        )

    # Add inverter numbers
    inverter_no = 1
    for inverter_id in coordinator.hub.inverter_slave_ids:
        inverter_name = f"Sigen { f'{plant_name.split()[1] } ' if plant_name.split()[1].isdigit() else ''}Inverter{'' if inverter_no == 1 else f' {inverter_no}'}"
        for description in INVERTER_NUMBERS:
            entities.append(
                SigenergyNumber(
                    coordinator=coordinator,
                    hub=hub,
                    description=description,
                    name=f"{plant_name} Inverter {inverter_id} {description.name}",
                    device_type=DEVICE_TYPE_INVERTER,
                    device_id=inverter_id,
                    device_name=inverter_name,
                )
            )
        inverter_no += 1

    # Add AC charger numbers
    ac_charger_no = 0
    for ac_charger_id in coordinator.hub.ac_charger_slave_ids:
        ac_charger_name=f"Sigen { f'{plant_name.split()[1] } ' if plant_name.split()[1].isdigit() else ''}AC Charger{'' if ac_charger_no == 0 else f' {ac_charger_no}'}"
        for description in AC_CHARGER_NUMBERS:
            entities.append(
                SigenergyNumber(
                    coordinator=coordinator,
                    hub=hub,
                    description=description,
                    name=f"{ac_charger_name} {description.name}",
                    device_type=DEVICE_TYPE_AC_CHARGER,
                    device_id=ac_charger_id,
                    device_name=ac_charger_name,
                )
            )
        ac_charger_no += 1

    # Add DC charger numbers
    dc_charger_no = 0
    # Iterate through the connection details dictionary
    for dc_charger_name, connection_details in coordinator.hub.dc_charger_connections.items():
        # Extract the slave ID from the details
        dc_charger_id = connection_details.get(CONF_SLAVE_ID)
        if dc_charger_id is None:
            _LOGGER.warning("Missing slave ID for DC charger '%s' in configuration, skipping number setup", dc_charger_name)
            continue

        _LOGGER.debug("Adding numbers for DC charger %s (ID: %s)", dc_charger_name, dc_charger_id)
        for description in DC_CHARGER_NUMBERS:
            entities.append(
                SigenergyNumber(
                    coordinator=coordinator,
                    hub=hub,
                    description=description,
                    name=f"{dc_charger_name} {description.name}",
                    device_type=DEVICE_TYPE_DC_CHARGER,
                    device_id=dc_charger_id,
                    device_name=dc_charger_name,
                )
            )
        dc_charger_no += 1

    async_add_entities(entities)


class SigenergyNumber(CoordinatorEntity, NumberEntity):
    """Representation of a Sigenergy number."""

    entity_description: SigenergyNumberEntityDescription

    def __init__(
        self,
        coordinator: SigenergyDataUpdateCoordinator,
        hub: Any,
        description: SigenergyNumberEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[int],
        device_name: Optional[str] = "",
    ) -> None:
        """Initialize the number."""
        super().__init__(coordinator)
        self.entity_description = description
        self.hub = hub
        self._attr_name = name
        self._device_type = device_type
        self._device_id = device_id
        
        # Get the device number if any as a string for use in names
        device_number_str = ""
        if device_name: # Check if device_name is not None or empty
            parts = device_name.split()
            if parts and parts[-1].isdigit():
                device_number_str = f" {parts[-1]}"

        # Set unique ID
        if device_type == DEVICE_TYPE_PLANT:
            # self._attr_unique_id = f"{coordinator.hub.host}_{device_type}_{description.key}"
            self._attr_unique_id = f"{coordinator.hub.config_entry.entry_id}_{device_type}_{description.key}"
        else:
            # self._attr_unique_id = f"{coordinator.hub.host}_{device_type}_{device_id}_{description.key}"
            # Used for testing in development to allow multiple sensors with the same unique ID
            self._attr_unique_id = f"{coordinator.hub.config_entry.entry_id}_{device_type}_{device_number_str}_{description.key}"
        
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
        elif device_type == DEVICE_TYPE_DC_CHARGER:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_{str(device_name).lower().replace(' ', '_')}")},
                name=device_name,
                manufacturer="Sigenergy",
                model="DC Charger",
                via_device=(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant"),
            )

    @property
    def native_value(self) -> float:
        """Return the value of the number."""
        if self.coordinator.data is None:
            return 0
            
        return self.entity_description.value_fn(self.coordinator.data, self._device_id)

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
        elif self._device_type == DEVICE_TYPE_DC_CHARGER:
            if not (
                self.coordinator.data is not None
                and "dc_chargers" in self.coordinator.data
                and self._device_id in self.coordinator.data["dc_chargers"]
            ):
                return False
                
            # Check if the entity has a specific availability function
            if hasattr(self.entity_description, "available_fn"):
                return self.entity_description.available_fn(self.coordinator.data, self._device_id)
                
            return True
            
        return False

    async def async_set_native_value(self, value: float) -> None:
        """Set the value of the number."""
        try:
            await self.entity_description.set_value_fn(self.hub, self._device_id, value)
            await self.coordinator.async_request_refresh()
        except SigenergyModbusError as error:
            _LOGGER.error("Failed to set value %s for %s: %s", value, self.name, error)