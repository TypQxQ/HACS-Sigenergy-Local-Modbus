"""Calculated sensor implementations for Sigenergy integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
    RestoreSensor,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
# from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfEnergy,
    EntityCategory,
    UnitOfPower,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import callback, State
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    EMSWorkMode,
    DEVICE_TYPE_PLANT,
    DEVICE_TYPE_INVERTER,
    DOMAIN,
)

from .common import (
    SigenergySensorEntityDescription,
    generate_device_id,
    generate_device_name,
)

_LOGGER = logging.getLogger(__name__)


class SigenergyCalculations:
    """Static class for Sigenergy calculated sensor functions."""
    
    # Class variable to store last power readings and timestamps for energy calculation
    _power_history = {}  # Format: {(device_id, pv_idx): {'last_timestamp': datetime, 'last_power': float, 'accumulated_energy': float}}
    
    @staticmethod
    def minutes_to_gmt(minutes: Any) -> Optional[str]:
        """Convert minutes offset to GMT format."""
        if minutes is None:
            return None
        try:
            hours = int(minutes) // 60
            return f"GMT{'+' if hours >= 0 else ''}{hours}"
        except (ValueError, TypeError):
            return None

    @staticmethod
    def epoch_to_datetime(epoch: Any, coordinator_data: Optional[dict] = None) -> Optional[datetime]:
        """Convert epoch timestamp to datetime using system's configured timezone."""
        # _LOGGER.debug("[CS][Timestamp] Converting epoch: %s (type: %s)", epoch, type(epoch))
        if epoch is None or epoch == 0:  # Also treat 0 as None for timestamps
            # _LOGGER.debug("[CS][Timestamp] Received null or zero timestamp")
            return None

        try:
            # Convert epoch to integer if it isn't already
            epoch_int = int(epoch)
            
            # Create timezone based on coordinator data if available
            if coordinator_data and "plant" in coordinator_data:
                try:
                    tz_offset = coordinator_data["plant"].get("plant_system_timezone")
                    # _LOGGER.debug("[CS][Timestamp] Found timezone offset: %s", tz_offset)
                    if tz_offset is not None:
                        tz_minutes = int(tz_offset)
                        tz_hours = tz_minutes // 60
                        tz_remaining_minutes = tz_minutes % 60
                        tz = timezone(timedelta(hours=tz_hours, minutes=tz_remaining_minutes))
                        # _LOGGER.debug("[CS][Timestamp] Calculated timezone: UTC%+d:%02d",
                                    # tz_hours, abs(tz_remaining_minutes))
                    else:
                        # _LOGGER.debug("[CS][Timestamp] No timezone offset found, using UTC")
                        tz = timezone.utc
                except (ValueError, TypeError) as e:
                    _LOGGER.warning("[CS][Timestamp] Invalid timezone offset in coordinator data: %s", e)
                    tz = timezone.utc
            else:
                # _LOGGER.debug("[CS][Timestamp] No plant data available, using UTC")
                tz = timezone.utc
                
            # Additional validation for timestamp range
            if epoch_int < 0 or epoch_int > 32503680000:  # Jan 1, 3000
                _LOGGER.warning("[CS][Timestamp] Value %s out of reasonable range [0, 32503680000]",
                              epoch_int)
                return None

            try:
                # Convert timestamp using the determined timezone
                dt = datetime.fromtimestamp(epoch_int, tz=tz)
                # _LOGGER.debug("[CS][Timestamp] Successfully converted %s to %s (timezone: %s)",
                            # epoch_int, dt.isoformat(), tz)
                return dt
            except (OSError, OverflowError) as ex:
                _LOGGER.warning("[CS][Timestamp] Invalid timestamp %s: %s", epoch_int, ex)
                return None
            
        except (ValueError, TypeError, OSError) as ex:
            _LOGGER.warning("[CS][Timestamp] Conversion error for %s: %s", epoch, ex)
            return None

    @staticmethod
    def calculate_pv_power(_, coordinator_data: Optional[Dict[str, Any]] = None, extra_params: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Calculate PV string power with proper error handling."""
        if not coordinator_data or not extra_params:
            _LOGGER.warning("Missing required data for PV power calculation")
            return None
            
        try:
            pv_idx = extra_params.get("pv_idx")
            # Expect device_name instead of device_id
            device_name = extra_params.get("device_name") 
            
            if not pv_idx or not device_name:
                _LOGGER.warning("Missing PV string index or device name for power calculation from extra_params: %s",
                            extra_params)
                return None
                
            # Use device_name to look up inverter data
            inverter_data = coordinator_data.get("inverters", {}).get(device_name, {})

            if not inverter_data:
                _LOGGER.warning("[CS][PV Power] No inverter data available for power calculation")
                return None
                
            v_key = f"inverter_pv{pv_idx}_voltage"
            c_key = f"inverter_pv{pv_idx}_current"
            
            pv_voltage = inverter_data.get(v_key)
            pv_current = inverter_data.get(c_key)
            
            # Validate inputs
            if pv_voltage is None or pv_current is None:
                _LOGGER.warning("[CS][PV Power] Missing voltage or current data for PV string %d", pv_idx)
                return None
                
            if not isinstance(pv_voltage, (int, float)) or not isinstance(pv_current, (int, float)):
                _LOGGER.warning("Invalid data types for PV string %d: voltage=%s, current=%s",
                            pv_idx, type(pv_voltage), type(pv_current))
                return None
                
            # Calculate power with bounds checking
            # Convert to Decimal for precise calculation
            try:
                voltage_dec = Decimal(str(pv_voltage))
                current_dec = Decimal(str(pv_current))
                power = voltage_dec * current_dec  # Already in Watts
            except (ValueError, TypeError, InvalidOperation):
                _LOGGER.warning("[CS][PV Power] Error converting values to Decimal: V=%s, I=%s", 
                              pv_voltage, pv_current)
                # Fallback to float calculation
                power = float(pv_voltage) * float(pv_current)
            
            # Apply some reasonable bounds
            MAX_REASONABLE_POWER = Decimal('20000')  # 20kW per string is very high already
            if isinstance(power, Decimal) and abs(power) > MAX_REASONABLE_POWER:
                _LOGGER.warning("[CS][PV Power] Calculated power for PV string %d seems excessive: %s W",
                            pv_idx, power)
            elif not isinstance(power, Decimal) and abs(power) > float(MAX_REASONABLE_POWER):
                _LOGGER.warning("[CS][PV Power] Calculated power for PV string %d seems excessive: %s W",
                            pv_idx, power)
            
            # Convert to kW
            if isinstance(power, Decimal):
                final_power = power / Decimal('1000')
            else:
                final_power = power / 1000
            
            # _LOGGER.debug("[CS][PV Power] Final power for PV%d: %s kW", pv_idx, final_power)
            return float(final_power) if isinstance(final_power, Decimal) else final_power
        except Exception as ex:
            _LOGGER.warning("[CS]Error calculating power for PV string %d: %s",
                        extra_params.get("pv_idx", "unknown"), ex)
            return None

    @staticmethod
    def calculate_grid_import_power(value, coordinator_data: Optional[Dict[str, Any]] = None, extra_params: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Calculate grid import power (positive values only)."""
        if coordinator_data is None or "plant" not in coordinator_data:
            # _LOGGER.debug("[CS][Grid Import] No plant data available")
            return None
            
        # Get the grid active power value from coordinator data
        grid_power = coordinator_data["plant"].get("plant_grid_sensor_active_power")
        # _LOGGER.debug("[CS][Grid Import] Starting calculation with grid_power=%s", grid_power)
        
        if grid_power is None or not isinstance(grid_power, (int, float)):
            # _LOGGER.debug("[CS][Grid Import] Invalid grid power value: %s", grid_power)
            return None
            
        # Convert to Decimal for precise calculation
        try:
            power_dec = Decimal(str(grid_power))
            # Return value if positive, otherwise 0
            return float(power_dec) if power_dec > Decimal('0') else 0
        except (ValueError, TypeError, InvalidOperation):
            # _LOGGER.debug("[CS][Grid Import] Error converting value to Decimal: %s", grid_power)
            # Fallback to float calculation
            return grid_power if grid_power > 0 else 0

    @staticmethod
    def calculate_grid_export_power(value, coordinator_data: Optional[Dict[str, Any]] = None, extra_params: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Calculate grid export power (negative values converted to positive)."""
        if coordinator_data is None or "plant" not in coordinator_data:
            # _LOGGER.debug("[CS][Grid Export] No plant data available")
            return None
            
        # Get the grid active power value from coordinator data
        grid_power = coordinator_data["plant"].get("plant_grid_sensor_active_power")
        # _LOGGER.debug("[CS][Grid Export] Starting calculation with grid_power=%s", grid_power)
        
        if grid_power is None or not isinstance(grid_power, (int, float)):
            # _LOGGER.debug("[CS][Grid Export] Invalid grid power value: %s", grid_power)
            return None
            
        # Convert to Decimal for precise calculation
        try:
            power_dec = Decimal(str(grid_power))
            # Return absolute value if negative, otherwise 0
            return float(-power_dec) if power_dec < Decimal('0') else 0
        except (ValueError, TypeError, InvalidOperation):
            # _LOGGER.debug("[CS][Grid Export] Error converting value to Decimal: %s", grid_power)
            # Fallback to float calculation
            return -grid_power if grid_power < 0 else 0

    @staticmethod
    def calculate_plant_consumed_power(value, coordinator_data: Optional[Dict[str, Any]] = None, extra_params: Optional[Dict[str, Any]] = None) -> Optional[float]:
        """Calculate plant consumed power (household/building consumption).
        
        Formula: PV Power + Grid Import Power - Grid Export Power - Plant Battery Power
        """
        # _LOGGER.debug("[CS][Plant Consumed] Starting calculation with coordinator_data=%s, extra_params=%s",
        #              bool(coordinator_data), extra_params)
        
        if coordinator_data is None or "plant" not in coordinator_data:
            # _LOGGER.debug("[CS][Plant Consumed] No plant data available")
            return None
            
        # Get the required values from coordinator data
        plant_data = coordinator_data["plant"]
        # _LOGGER.debug("[CS][Plant Consumed] Plant data keys: %s", list(plant_data.keys()))
        
        # Get PV power
        pv_power = plant_data.get("plant_photovoltaic_power")
        # _LOGGER.debug("[CS][Plant Consumed] PV power: %s (type: %s)", 
        #              pv_power, type(pv_power).__name__ if pv_power is not None else "None")
        
        # Get grid active power and calculate import/export
        grid_power = plant_data.get("plant_grid_sensor_active_power")
        # _LOGGER.debug("[CS][Plant Consumed] Grid power: %s (type: %s)", 
        #              grid_power, type(grid_power).__name__ if grid_power is not None else "None")
        
        # Get battery power
        battery_power = plant_data.get("plant_ess_power")
        # _LOGGER.debug("[CS][Plant Consumed] Battery power: %s (type: %s)", 
        #              battery_power, type(battery_power).__name__ if battery_power is not None else "None")
        
        # Validate inputs
        if pv_power is None or grid_power is None or battery_power is None:
            # _LOGGER.debug("[CS][Plant Consumed] Missing required power values: PV=%s, Grid=%s, Battery=%s",
            #             pv_power, grid_power, battery_power)
            return None
        
        # Validate input types
        if not isinstance(pv_power, (int, float)):
            # _LOGGER.warning("[CS][Plant Consumed] PV power is not a number: %s (type: %s)", 
            #               pv_power, type(pv_power).__name__)
            return None
        if not isinstance(grid_power, (int, float)):
            _LOGGER.warning("[CS][Plant Consumed] Grid power is not a number: %s (type: %s)", 
                          grid_power, type(grid_power).__name__)
            return None
        if not isinstance(battery_power, (int, float)):
            _LOGGER.warning("[CS][Plant Consumed] Battery power is not a number: %s (type: %s)", 
                          battery_power, type(battery_power).__name__)
            return None
        
        # Calculate grid import and export power
        # Grid power is positive when importing, negative when exporting
        grid_import = max(0, grid_power)
        grid_export = max(0, -grid_power)
        # _LOGGER.debug("[CS][Plant Consumed] Calculated Grid Import: %s, Grid Export: %s",
        #              grid_import, grid_export)
        
        # Calculate plant consumed power
        # Note: battery_power is positive when charging, negative when discharging
        try:
            consumed_power = pv_power + grid_import - grid_export - battery_power
            # _LOGGER.debug("[CS][Plant Consumed] Raw calculation: %s + %s - %s - %s = %s",
            #             pv_power, grid_import, grid_export, battery_power, consumed_power)
            
            # Sanity check
            if consumed_power < 0:
                _LOGGER.warning("[CS][Plant Consumed] Calculated power is negative: %s kW", consumed_power)
                # Keep the negative value as it might be valid in some scenarios
            
            if consumed_power > 50:  # Unlikely to have consumption over 50 kW in residential setting
                _LOGGER.warning("[CS][Plant Consumed] Calculated power seems excessive: %s kW", consumed_power)
        except Exception as ex:
            _LOGGER.error("[CS][Plant Consumed] Error during calculation: %s", ex, exc_info=True)
            return None
        
        # _LOGGER.debug("[CS][Plant Consumed] Final calculated power: %s kW", consumed_power)
        return consumed_power

class IntegrationTrigger(Enum):
    """Trigger type for integration calculations."""
    
    STATE_EVENT = "state_event"
    TIME_ELAPSED = "time_elapsed"


class SigenergyIntegrationSensor(CoordinatorEntity, RestoreSensor):
    """Implementation of an Integration Sensor with identical behavior to HA core."""
    
    _attr_state_class = SensorStateClass.TOTAL
    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        description: SensorEntityDescription,
        name: str,
        device_type: str,
        device_id: Optional[int],
        device_name: Optional[str] = "",
        device_info: Optional[DeviceInfo] = None,
        source_entity_id: Optional[str] = None,
        # max_sub_interval: Optional[timedelta] = None,
        pv_string_idx: Optional[int] = None,
    ) -> None:
        """Initialize the integration sensor."""
        CoordinatorEntity.__init__(self, coordinator)
        RestoreSensor.__init__(self)
        self.entity_description = description
        self._attr_name = name
        self._device_type = device_type
        self._device_id = device_id # Keep slave ID if needed
        self._device_name = device_name # Store device name
        self._device_info_override = device_info
        self._source_entity_id = source_entity_id
        self._pv_string_idx = pv_string_idx
        self._round_digits = None
        
        if hasattr(description, 'round_digits') and description.round_digits is not None:
            self._round_digits = description.round_digits

        if hasattr(description, 'max_sub_interval') and description.max_sub_interval is not None:
            self._max_sub_interval = description.max_sub_interval

        # Initialize state variables
        self._state: Decimal | None = None
        self._last_valid_state: Decimal | None = None
        
        # Time tracking variables
        self._max_sub_interval = (
            None  # disable time based integration
            if self._max_sub_interval is None or self._max_sub_interval.total_seconds() == 0
            else self._max_sub_interval
        )
        # _LOGGER.debug("[Callback] Initializing integration sensor %s with max_sub_interval=%s",
                    # name, self._max_sub_interval)
        self._max_sub_interval_exceeded_callback = lambda *args: None
        self._cancel_max_sub_interval_exceeded_callback = self._max_sub_interval_exceeded_callback
        self._last_integration_time = dt_util.utcnow()
        self._last_integration_trigger = IntegrationTrigger.STATE_EVENT

        # _LOGGER.debug("[CS][Integration] Created sensor %s with max_sub_interval: %s", 
        #               name, self._max_sub_interval)
        
        # Set device info
        if self._device_info_override:
            self._attr_device_info = self._device_info_override
        else:
            # Use the same device info logic as in SigenergySensor class
            if device_type == DEVICE_TYPE_PLANT:
                self._attr_device_info = DeviceInfo(
                    identifiers={(DOMAIN, f"{coordinator.hub.config_entry.entry_id}_plant")},
                    name=device_name, # Should be plant_name
                    manufacturer="Sigenergy",
                    model="Energy Storage System",
                )
            elif device_type == DEVICE_TYPE_INVERTER:
                # Get model and serial number if available
                model = None
                serial_number = None
                sw_version = None
                if coordinator.data and "inverters" in coordinator.data:
                    # Use device_name (inverter_name) to fetch data
                    inverter_data = coordinator.data["inverters"].get(device_name, {}) 
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

    def _decimal_state(self, state: str) -> Optional[Decimal]:
        """Convert state to Decimal or return None if not possible."""
        try:
            decimal_value = Decimal(state)
            # _LOGGER.debug("[CS][State] Converted %s to Decimal: %s", state, decimal_value)
            return decimal_value
        except (InvalidOperation, TypeError) as e:
            _LOGGER.warning("[CS][State] Failed to convert %s to Decimal: %s", state, e)
            return None

    def _validate_states(self, left: str, right: str) -> Optional[tuple[Decimal, Decimal]]:
        """Validate states and convert to Decimal."""
        # _LOGGER.debug("[CS][State] Validating states - Left: %s, Right: %s", left, right)
        if (left_dec := self._decimal_state(left)) is None or (right_dec := self._decimal_state(right)) is None:
            # _LOGGER.debug("[CS][State] State validation failed - Left: %s, Right: %s",
            #             left_dec, right_dec)
            return None
        # _LOGGER.debug("[CS][State] States validated - Left: %s, Right: %s", left_dec, right_dec)
        return (left_dec, right_dec)

    def _calculate_trapezoidal(self, elapsed_time: Decimal, left: Decimal, right: Decimal) -> Decimal:
        """Calculate area using the trapezoidal method."""
        return elapsed_time * (left + right) / Decimal(2)

    def _calculate_area_with_one_state(self, elapsed_time: Decimal, constant_state: Decimal) -> Decimal:
        """Calculate area given one state (constant value)."""
        return constant_state * elapsed_time

    def _update_integral(self, area: Decimal) -> None:
        """Update the integral with the calculated area."""
        # Convert seconds to hours
        area_scaled = area / Decimal(3600)
        
        if isinstance(self._state, Decimal):
            self._state += area_scaled
        else:
            self._state = area_scaled
            
        # _LOGGER.debug(
        #     "area = %s, area_scaled = %s new state = %s", area, area_scaled, self._state
        # )
        self._last_valid_state = self._state

    def _setup_midnight_reset(self) -> None:
        """Schedule reset at midnight."""
        now = dt_util.now()
        midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        @callback
        def _handle_midnight(current_time):
            """Handle midnight reset."""
            self._state = Decimal(0)
            self._last_valid_state = self._state
            self.async_write_ha_state()
            self._setup_midnight_reset()  # Schedule next reset
            
        # Schedule the reset
        self.async_on_remove(
            async_track_point_in_time(
                self.hass, _handle_midnight, midnight
            )
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        
        # Restore previous state if available
        last_state = await self.async_get_last_state()
        # _LOGGER.debug("[CS][Integration] Attempting to restore state for %s: %s",
        #              self.entity_id, last_state.state if last_state else None)
        if last_state and last_state.state not in (None, STATE_UNKNOWN, STATE_UNAVAILABLE):
            try:
                self._state = Decimal(last_state.state)
                self._last_valid_state = self._state
                self._last_integration_time = dt_util.utcnow()
            except (ValueError, TypeError, InvalidOperation):
                _LOGGER.warning("Could not restore last state for %s", self.entity_id)
        
        # Set up appropriate handlers based on max_sub_interval
        # Ensure source_entity_id is valid before proceeding
        if not isinstance(self._source_entity_id, str):
            _LOGGER.error("Source entity ID is not a valid string for %s: %s", self.entity_id, self._source_entity_id)
            return # Cannot set up tracking without a valid source ID
            
        if self._max_sub_interval is not None:
            source_state = self.hass.states.get(self._source_entity_id)
            # _LOGGER.debug("[Callback] Setting up max interval handling for %s with source state %s",
            #            self.entity_id, source_state.state if source_state else None)
            self._schedule_max_sub_interval_exceeded_if_state_is_numeric(source_state)
            self.async_on_remove(self._cancel_max_sub_interval_exceeded_callback)
            handle_state_change = self._integrate_on_state_change_with_max_sub_interval
        else:
            handle_state_change = self._integrate_on_state_change_callback
        
        # Check if source entity exists
        # source_entity = self.hass.states.get(self._source_entity_id)
        # _LOGGER.debug("[CS][Integration] Source entity %s exists: %s, state: %s",
        #              self._source_entity_id,
        #              source_entity is not None,
        #              source_entity.state if source_entity else "N/A")
 # Use the checked source_entity_id
                     
        # Add more detailed logging about the source entity
        # _LOGGER.debug("[CS][Integration] All available entities with 'sigen' in the name:")
        # for state in self.hass.states.async_all():
        #     if 'sigen' in state.entity_id:
        #         _LOGGER.debug("  - %s: %s", state.entity_id, state.state)
        
        # Check source entity and log potential alternatives
        self._check_source_entity()
        
        # Set up midnight reset for daily sensors
        if "daily" in self.entity_description.key:
            self._setup_midnight_reset()

        # Register to track source sensor state changes
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._source_entity_id], handle_state_change
 # Use the checked source_entity_id
            )
        )

    @callback
    def _integrate_on_state_change_callback(self, event) -> None:
        """Handle sensor state change without max_sub_interval."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        
        self._integrate_on_state_change(old_state, new_state)

    @callback
    def _integrate_on_state_change_with_max_sub_interval(self, event) -> None:
        """Handle sensor state change with max_sub_interval."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        # Cancel any pending callbacks
        # _LOGGER.debug("[Callback] Cancelling pending callbacks for %s due to state change",
        #            self.entity_id)
        self._cancel_max_sub_interval_exceeded_callback()
        
        
        try:
            self._integrate_on_state_change(old_state, new_state)
            self._last_integration_trigger = IntegrationTrigger.STATE_EVENT
            self._last_integration_time = dt_util.utcnow()
        finally:
            # Schedule the next time-based integration
            self._schedule_max_sub_interval_exceeded_if_state_is_numeric(new_state)

    def _integrate_on_state_change(self, old_state: State | None, new_state: State | None) -> None:
        """Perform integration based on state change."""
        if new_state is None:
            return
            
        if new_state.state == STATE_UNAVAILABLE:
            self._attr_available = False
            self.async_write_ha_state()
            return
            
        self._attr_available = True
        
        if old_state is None or old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self.async_write_ha_state()
            return
            
        # Validate states
        if not (states := self._validate_states(old_state.state, new_state.state)):
            self.async_write_ha_state()
            return
            
        # Calculate elapsed time
        elapsed_seconds = Decimal(
            (new_state.last_updated - old_state.last_updated).total_seconds()
            if self._last_integration_trigger == IntegrationTrigger.STATE_EVENT
            else (new_state.last_updated - self._last_integration_time).total_seconds()
        )
        # _LOGGER.debug("[CS][Integration] Calculating for %s - Time delta: %s seconds, Trigger: %s",
        #             self.entity_id, elapsed_seconds, self._last_integration_trigger)
        # _LOGGER.debug("[CS][Integration] States - Old: %s, New: %s",
        #             old_state.state if old_state else None,
        #             new_state.state if new_state else None
        # )
        
        # Calculate area
        area = self._calculate_trapezoidal(elapsed_seconds, *states)
        
        # Update the integral
        self._update_integral(area)
        self.async_write_ha_state()

    def _schedule_max_sub_interval_exceeded_if_state_is_numeric(self, source_state: State | None) -> None:
        """Schedule integration based on max_sub_interval."""
        # _LOGGER.debug("[CS][State] Scheduling check for %s - max_interval: %s, source_state: %s",
        #             self.entity_id, self._max_sub_interval,
        #             source_state.state if source_state else None)
        if (
            self._max_sub_interval is not None
            and source_state is not None
            and (source_state_dec := self._decimal_state(source_state.state)) is not None
        ):
            @callback
            def _integrate_on_max_sub_interval_exceeded_callback(now: datetime) -> None:
                """Integrate based on time and reschedule."""
                # _LOGGER.debug("[CS][Integration] Max interval exceeded for %s at %s",
                #           self.entity_id, now)
                elapsed_seconds = Decimal(
                    (now - self._last_integration_time).total_seconds()
                )
                # _LOGGER.debug("[CS][Integration] Time-based calculation - Elapsed: %s seconds, State: %s",
                #           elapsed_seconds, source_state_dec)
                
                # Calculate area with constant state
                area = self._calculate_area_with_one_state(elapsed_seconds, source_state_dec)
                
                # Update the integral
                self._update_integral(area)
                self.async_write_ha_state()
                
                # Update tracking variables
                self._last_integration_time = dt_util.utcnow()
                self._last_integration_trigger = IntegrationTrigger.TIME_ELAPSED
                
                # Schedule the next integration
                self._schedule_max_sub_interval_exceeded_if_state_is_numeric(source_state)
                
            # Schedule the callback
            self._max_sub_interval_exceeded_callback = async_call_later(
                self.hass,
                self._max_sub_interval,
                _integrate_on_max_sub_interval_exceeded_callback,
            )
    def _cancel_max_sub_interval_exceeded_callback(self) -> None:
        """Cancel the scheduled callback."""
        # _LOGGER.debug("[CS][State] Cancelling scheduled callback for %s", self.entity_id)
        self._max_sub_interval_exceeded_callback()


    @property
    def native_value(self) -> Decimal | None:
        """Return the state of the sensor."""
        value = (
            round(self._state, self._round_digits)
            if isinstance(self._state, Decimal) and self._round_digits is not None
            else self._state
        )
        # _LOGGER.debug("[CS][State] %s value: %s (type: %s)",
                    # self.entity_id, value,
                    # type(value).__name__ if value is not None else 'None')
        return value
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes of the sensor."""
        return {
            "source_entity": self._source_entity_id,
        }
    
    def _check_source_entity(self) -> None:
        """Check if the source entity exists and log potential alternatives."""
        source_entity = self.hass.states.get(self._source_entity_id) if self._source_entity_id else None # Check for None
        # _LOGGER.debug("[CS][Diagnostic] Source entity check for %s:", self.entity_id)
        # _LOGGER.debug("  - Expected source: %s", self._source_entity_id)
        # _LOGGER.debug("  - Source exists: %s", source_entity is not None)
        # _LOGGER.debug("  - Source state: %s", source_entity.state if source_entity else "N/A")
        
        # If source doesn't exist, look for similar entities
        if source_entity is None:
            # Extract key parts from the entity description
            source_key = getattr(self.entity_description, "source_key", "")
            device_type = self._device_type.lower().replace("_", "")
            
            # _LOGGER.debug("  - Source key: %s", source_key)
            # _LOGGER.debug("  - Device type: %s", device_type)
            
            # Look for entities with similar names
            similar_entities = []
            exact_match_entities = []
            pattern_match_entities = []
            
            for state in self.hass.states.async_all():
                entity_id = state.entity_id.lower()
                
                # Skip non-sensor entities
                if not entity_id.startswith("sensor."):
                    continue
                    
                # Skip self
                if entity_id == self.entity_id.lower():
                    continue
                
                # Check for exact matches first
                if source_key and source_key in entity_id and device_type in entity_id:
                    exact_match_entities.append((state.entity_id, state.state))
                    continue
                    
                # Check for pattern matches
                if entity_id.startswith("sensor.sigen"):
                    # For plant entities
                    if device_type == "plant" and "plant" in entity_id:
                        if source_key and source_key in entity_id:
                            pattern_match_entities.append((state.entity_id, state.state))
                        elif "pv" in source_key and "pv" in entity_id and "power" in entity_id:
                            pattern_match_entities.append((state.entity_id, state.state))
                        elif "grid" in source_key and "grid" in entity_id:
                            if "import" in source_key and "import" in entity_id:
                                pattern_match_entities.append((state.entity_id, state.state))
                            elif "export" in source_key and "export" in entity_id:
                                pattern_match_entities.append((state.entity_id, state.state))
                    
                    # For inverter entities
                    elif device_type == "inverter" and "inverter" in entity_id:
                        if source_key and source_key in entity_id:
                            pattern_match_entities.append((state.entity_id, state.state))
                        elif "pv" in source_key and "pv" in entity_id and "power" in entity_id:
                            pattern_match_entities.append((state.entity_id, state.state))
                    
                    # Add any other sigen entities as general matches
                    similar_entities.append((state.entity_id, state.state))
            
            # Log the results
            # if exact_match_entities:
            #     _LOGGER.debug("  - Exact match entities:")
            #     for entity_id, state in exact_match_entities:
            #         _LOGGER.debug("    * %s (state: %s)", entity_id, state)
                    
            # if pattern_match_entities:
            #     _LOGGER.debug("  - Pattern match entities:")
            #     for entity_id, state in pattern_match_entities:
            #         _LOGGER.debug("    * %s (state: %s)", entity_id, state)
                    
            # if not exact_match_entities and not pattern_match_entities and similar_entities:
            #     _LOGGER.debug("  - Other Sigen entities:")
            #     for entity_id, state in similar_entities[:10]:  # Limit to 10 to avoid log spam
            #         _LOGGER.debug("    * %s (state: %s)", entity_id, state)
                    
            # if not exact_match_entities and not pattern_match_entities and not similar_entities:
            #     _LOGGER.debug("  - No potential alternative sources found")
                
            # Suggest the best alternative
            if exact_match_entities:
                _LOGGER.warning("  - Suggested alternative: %s", exact_match_entities[0][0])
            elif pattern_match_entities:
                _LOGGER.warning("  - Suggested alternative: %s", pattern_match_entities[0][0])



class SigenergyCalculatedSensors:
    """Class for holding calculated sensor methods."""

    PV_STRING_SENSORS = [
        SigenergySensorEntityDescription(
            key="power",
            name="Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=SigenergyCalculations.calculate_pv_power,
            extra_fn_data=True,
            suggested_display_precision=2,
            round_digits=6,
        ),
    ]

    PLANT_SENSORS = [
        # System time and timezone
        SigenergySensorEntityDescription(
            key="plant_system_time",
            name="System Time",
            icon="mdi:clock",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            # Adapt function signature to match expected value_fn
            value_fn=lambda value, coord_data, _: SigenergyCalculations.epoch_to_datetime(value, coord_data),
            extra_fn_data=True,  # Indicates that this sensor needs coordinator data for timestamp conversion
        ),
        SigenergySensorEntityDescription(
            key="plant_system_timezone",
            name="System Timezone",
            icon="mdi:earth",
            entity_category=EntityCategory.DIAGNOSTIC,
            # Adapt function signature
            value_fn=lambda value, _, __: SigenergyCalculations.minutes_to_gmt(value),
        ),
        # EMS Work Mode sensor with value mapping
        SigenergySensorEntityDescription(
            key="plant_ems_work_mode",
            name="EMS Work Mode",
            icon="mdi:home-battery",
            # Adapt function signature
            value_fn=lambda value, _, __: {
                EMSWorkMode.MAX_SELF_CONSUMPTION: "Maximum Self Consumption",
                EMSWorkMode.AI_MODE: "AI Mode",
                EMSWorkMode.TOU: "Time of Use",
                EMSWorkMode.REMOTE_EMS: "Remote EMS",
            }.get(value, "Unknown"),
        ),
        SigenergySensorEntityDescription(
            key="plant_grid_import_power",
            name="Grid Import Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:power",
            value_fn=SigenergyCalculations.calculate_grid_import_power,
            extra_fn_data=True,  # Pass coordinator data to value_fn
            suggested_display_precision=2,
            round_digits=6,
        ),
        SigenergySensorEntityDescription(
            key="plant_grid_export_power",
            name="Grid Export Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:power",
            value_fn=SigenergyCalculations.calculate_grid_export_power,
            extra_fn_data=True,  # Pass coordinator data to value_fn
            suggested_display_precision=2,
            round_digits=6,
        ),
        SigenergySensorEntityDescription(
            key="plant_consumed_power",
            name="Consumed Power",
            device_class=SensorDeviceClass.POWER,
            native_unit_of_measurement=UnitOfPower.KILO_WATT,
            state_class=SensorStateClass.MEASUREMENT,
            icon="mdi:home-lightning-bolt",
            value_fn=SigenergyCalculations.calculate_plant_consumed_power,
            extra_fn_data=True,  # Pass coordinator data to value_fn
            suggested_display_precision=2,
            round_digits=6,
        ),
    ]

    INVERTER_SENSORS = [
        SigenergySensorEntityDescription(
            key="inverter_startup_time",
            name="Startup Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            # Adapt function signature
            value_fn=lambda value, coord_data, _: SigenergyCalculations.epoch_to_datetime(value, coord_data),
            extra_fn_data=True,  # Indicates that this sensor needs coordinator data for timestamp conversion
        ),
        SigenergySensorEntityDescription(
            key="inverter_shutdown_time",
            name="Shutdown Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            # Adapt function signature
            value_fn=lambda value, coord_data, _: SigenergyCalculations.epoch_to_datetime(value, coord_data),
            extra_fn_data=True,  # Indicates that this sensor needs coordinator data for timestamp conversion
        ),
    ]

    AC_CHARGER_SENSORS = []

    DC_CHARGER_SENSORS = []

    # Add the plant integration sensors list
    PLANT_INTEGRATION_SENSORS = [
        SigenergySensorEntityDescription(
            key="plant_accumulated_pv_energy",
            name="Accumulated PV Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
            source_key="plant_photovoltaic_power",  # Key of the source entity to use
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_accumulated_grid_export_energy",
            name="Accumulated Grid Export Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
            source_key="plant_grid_export_power",  # Key matches the calculated sensor
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_accumulated_grid_import_energy",
            name="Accumulated Grid Import Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
            source_key="plant_grid_import_power",  # Key matches the calculated sensor
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_daily_grid_export_energy",
            name="Daily Grid Export Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL_INCREASING,
            source_key="plant_grid_export_power",  # Key matches the grid export power sensor
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_daily_grid_import_energy",
            name="Daily Grid Import Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL_INCREASING,
            source_key="plant_grid_import_power",  # Key matches the grid import power sensor
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_daily_pv_energy",
            name="Daily PV Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL_INCREASING,
            source_key="plant_photovoltaic_power",  # Key matches the PV power sensor
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_accumulated_consumed_energy",
            name="Accumulated Consumed Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
            source_key="plant_consumed_power",  # Key of the source entity to use
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
        SigenergySensorEntityDescription(
            key="plant_daily_consumed_energy",
            name="Daily Consumed Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL_INCREASING,
            source_key="plant_consumed_power",  # Key of the source entity to use
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
    ]
    
    # Add the inverter integration sensors list
    INVERTER_INTEGRATION_SENSORS = [
        SigenergySensorEntityDescription(
            key="inverter_accumulated_pv_energy",
            name="Accumulated PV Energy",
            device_class=SensorDeviceClass.ENERGY,
            native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
            suggested_display_precision=2,
            state_class=SensorStateClass.TOTAL,
            source_key="inverter_pv_power",  # Key matches the sensor in static_sensor.py
            round_digits=6,
            max_sub_interval=timedelta(seconds=30),
        ),
    ]