"""Static sensors for Sigenergy."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry  #pylint: disable=no-name-in-module, syntax-error
from homeassistant.const import (
    CONF_NAME,
    EntityCategory,
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEVICE_TYPE_AC_CHARGER,
    DEVICE_TYPE_DC_CHARGER,
    DEVICE_TYPE_INVERTER,
    DEVICE_TYPE_PLANT,
    DOMAIN,
    EMSWorkMode,
    RunningState,
)

_LOGGER = logging.getLogger(__name__)

class StaticSensors:

    # PV string sensor descriptions
    PV_STRING_SENSORS = [
        SensorEntityDescription(
            key="voltage",
            name="Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="current",
            name="Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ]

    PLANT_SENSORS = [
        SensorEntityDescription(
            key="plant_grid_sensor_status",
            name="Grid Sensor Status",
            icon="mdi:power-plug",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_active_power",
            name="Grid Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_reactive_power",
            name="Grid Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_on_off_grid_status",
            name="Grid Connection Status",
            icon="mdi:transmission-tower",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Max power metrics
        SensorEntityDescription(
            key="plant_max_active_power",
            name="Max Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_max_apparent_power",
            name="Max Apparent Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_soc",
            name="Battery State of Charge",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        # Phase-specific active power
        SensorEntityDescription(
            key="plant_phase_a_active_power",
            name="Phase A Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_phase_b_active_power",
            name="Phase B Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_phase_c_active_power",
            name="Phase C Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Phase-specific reactive power
        SensorEntityDescription(
            key="plant_phase_a_reactive_power",
            name="Phase A Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_phase_b_reactive_power",
            name="Phase B Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_phase_c_reactive_power",
            name="Phase C Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Alarm registers
        SensorEntityDescription(
            key="plant_general_alarm1",
            name="General Alarm 1",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_general_alarm2",
            name="General Alarm 2",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_general_alarm3",
            name="General Alarm 3",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_general_alarm4",
            name="General Alarm 4",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_general_alarm5",
            name="General Alarm 5",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_active_power",
            name="Plant Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="plant_reactive_power",
            name="Plant Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_photovoltaic_power",
            name="PV Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="plant_ess_power",
            name="Battery Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="plant_ess_available_max_charging_power",
            name="Available Max Charging Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_available_max_discharging_power",
            name="Available Max Discharging Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_running_state",
            name="Plant Running State",
            icon="mdi:power",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Grid sensor phase-specific metrics
        SensorEntityDescription(
            key="plant_grid_sensor_phase_a_active_power",
            name="Grid Phase A Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_phase_b_active_power",
            name="Grid Phase B Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_phase_c_active_power",
            name="Grid Phase C Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_phase_a_reactive_power",
            name="Grid Phase A Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_phase_b_reactive_power",
            name="Grid Phase B Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_grid_sensor_phase_c_reactive_power",
            name="Grid Phase C Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # ESS rated power metrics
        SensorEntityDescription(
            key="plant_ess_rated_charging_power",
            name="ESS Rated Charging Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_rated_discharging_power",
            name="ESS Rated Discharging Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_available_max_charging_capacity",
            name="Available Max Charging Capacity",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_available_max_discharging_capacity",
            name="Available Max Discharging Capacity",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_rated_energy_capacity",
            name="Rated Energy Capacity",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_charge_cut_off_soc",
            name="Charge Cut-Off SOC",
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_discharge_cut_off_soc",
            name="Discharge Cut-Off SOC",
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="plant_ess_soh",
            name="Battery State of Health",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]

    INVERTER_SENSORS = [
        # Power ratings
        SensorEntityDescription(
            key="inverter_model_type",
            name="Model Type",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_serial_number",
            name="Serial Number",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_machine_firmware_version",
            name="Firmware Version",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_rated_active_power",
            name="Rated Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_max_apparent_power",
            name="Max Apparent Power",
            native_unit_of_measurement="kVA",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_max_active_power",
            name="Max Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_max_absorption_power",
            name="Max Absorption Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_rated_battery_capacity",
            name="Rated Battery Capacity",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_rated_charge_power",
            name="ESS Rated Charge Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_rated_discharge_power",
            name="ESS Rated Discharge Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_daily_charge_energy",
            name="Daily Charge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        SensorEntityDescription(
            key="inverter_ess_accumulated_charge_energy",
            name="Total Charge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        SensorEntityDescription(
            key="inverter_ess_daily_discharge_energy",
            name="Daily Discharge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        SensorEntityDescription(
            key="inverter_ess_accumulated_discharge_energy",
            name="Total Discharge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        SensorEntityDescription(
            key="inverter_running_state",
            name="Running State",
            icon="mdi:power",
        ),
        # Power adjustment values
        SensorEntityDescription(
            key="inverter_max_active_power_adjustment_value",
            name="Max Active Power Adjustment",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_min_active_power_adjustment_value",
            name="Min Active Power Adjustment",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_max_reactive_power_adjustment_value_fed",
            name="Max Reactive Power Fed",
            native_unit_of_measurement="kVar",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_max_reactive_power_adjustment_value_absorbed",
            name="Max Reactive Power Absorbed",
            native_unit_of_measurement="kVar",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_active_power",
            name="Active Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="inverter_reactive_power",
            name="Reactive Power",
            native_unit_of_measurement="kVar",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_charge_discharge_power",
            name="Battery Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        # Battery power metrics
        SensorEntityDescription(
            key="inverter_ess_max_battery_charge_power",
            name="Max Battery Charge Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_max_battery_discharge_power",
            name="Max Battery Discharge Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_available_battery_charge_energy",
            name="Available Battery Charge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_available_battery_discharge_energy",
            name="Available Battery Discharge Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_battery_soc",
            name="Battery State of Charge",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="inverter_ess_battery_soh",
            name="Battery State of Health",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_average_cell_temperature",
            name="Battery Average Cell Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_average_cell_voltage",
            name="Battery Average Cell Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_maximum_battery_temperature",
            name="Battery Maximum Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_minimum_battery_temperature",
            name="Battery Minimum Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_maximum_battery_cell_voltage",
            name="Battery Maximum Cell Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ess_minimum_battery_cell_voltage",
            name="Battery Minimum Cell Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Alarm registers
        SensorEntityDescription(
            key="inverter_alarm1",
            name="Alarm 1",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_alarm2",
            name="Alarm 2",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_alarm3",
            name="Alarm 3",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_alarm4",
            name="Alarm 4",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_alarm5",
            name="Alarm 5",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_grid_frequency",
            name="Grid Frequency",
            device_class=SensorDeviceClass.FREQUENCY,
            native_unit_of_measurement=UnitOfFrequency.HERTZ,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_pcs_internal_temperature",
            name="PCS Internal Temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_output_type",
            name="Output Type",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Grid metrics
        SensorEntityDescription(
            key="inverter_rated_grid_voltage",
            name="Rated Grid Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_rated_grid_frequency",
            name="Rated Grid Frequency",
            device_class=SensorDeviceClass.FREQUENCY,
            native_unit_of_measurement=UnitOfFrequency.HERTZ,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Line voltages
        SensorEntityDescription(
            key="inverter_ab_line_voltage",
            name="A-B Line Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_bc_line_voltage",
            name="B-C Line Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_ca_line_voltage",
            name="C-A Line Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_a_voltage",
            name="Phase A Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_b_voltage",
            name="Phase B Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_c_voltage",
            name="Phase C Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_a_current",
            name="Phase A Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_b_current",
            name="Phase B Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_phase_c_current",
            name="Phase C Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_power_factor",
            name="Power Factor",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # PV system metrics
        SensorEntityDescription(
            key="inverter_pack_count",
            name="PACK Count",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_pv_string_count",
            name="PV String Count",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_mppt_count",
            name="MPPT Count",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="inverter_pv_power",
            name="PV Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="inverter_insulation_resistance",
            name="Insulation Resistance",
            native_unit_of_measurement="MΩ",
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]
    AC_CHARGER_SENSORS = [
        SensorEntityDescription(
            key="ac_charger_system_state",
            name="System State",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="ac_charger_total_energy_consumed",
            name="Total Energy Consumed",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL_INCREASING,
        ),
        SensorEntityDescription(
            key="ac_charger_charging_power",
            name="Charging Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="ac_charger_rated_power",
            name="Rated Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="ac_charger_rated_current",
            name="Rated Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="ac_charger_rated_voltage",
            name="Rated Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Additional AC charger metrics
        SensorEntityDescription(
            key="ac_charger_input_breaker_rated_current",
            name="Input Breaker Rated Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        # Alarm registers
        SensorEntityDescription(
            key="ac_charger_alarm1",
            name="Alarm 1",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="ac_charger_alarm2",
            name="Alarm 2",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
        SensorEntityDescription(
            key="ac_charger_alarm3",
            name="Alarm 3",
            icon="mdi:alert",
            entity_category=EntityCategory.DIAGNOSTIC,
        ),
    ]

    DC_CHARGER_SENSORS = [
        SensorEntityDescription(
            key="dc_charger_vehicle_battery_voltage",
            name="DC Charger Vehicle Battery Voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="dc_charger_charging_current",
            name="DC Charger Charging Current",
            device_class=SensorDeviceClass.CURRENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="dc_charger_output_power",
            name="DC Charger Output Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="dc_charger_vehicle_soc",
            name="DC Charger Vehicle SOC",
            device_class=SensorDeviceClass.BATTERY,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="dc_charger_current_charging_capacity",
            name="DC Charger Current Charging Capacity (Single Time)",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            state_class=SensorStateClass.TOTAL,
        ),
        SensorEntityDescription(
            key="dc_charger_current_charging_duration",
            name="DC Charger Current Charging Duration (Single Time)",
            icon="mdi:timer",
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ]
