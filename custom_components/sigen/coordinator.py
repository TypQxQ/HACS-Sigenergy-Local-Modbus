"""Data update coordinator for Sigenergy ESS."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, TYPE_CHECKING

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # pylint: disable=syntax-error
from homeassistant.util import dt as dt_util

from .modbus import SigenergyModbusHub
if TYPE_CHECKING:
    from .calculated_sensor import SigenergyIntegrationSensor

_LOGGER = logging.getLogger(__name__)


class SigenergyDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the Sigenergy ESS."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        hub: SigenergyModbusHub,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialize."""
        self.hub = hub
        self.platforms: list = []
        self.integration_sensors: list[SigenergyIntegrationSensor] = [] # Added list for integration sensors

        super().__init__(
            hass,
            logger,
            name=name,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data via Modbus library."""
        try:
            async with async_timeout.timeout(60):
                _LOGGER.debug("Fetching data from Sigenergy system by Modbus")
                start_time = dt_util.utcnow()

                # Fetch plant data
                plant_data = await self.hub.async_read_plant_data()

                for plant_integrated_sensors in [None]:  # Placeholder for actual integrated sensors
                    # Call _integrate_on_state_change of the integrated sensors
                    # This is a placeholder for the actual integration logic
                    # await plant_integrated_sensors._integrate_on_state_change()
                    _LOGGER.debug("Called _integrate_on_state_change for integrated sensor: %s", plant_integrated_sensors)

                _LOGGER.debug("Fetched plant data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Fetch inverter data for each inverter
                inverter_data = {}
                for inverter_name in self.hub.inverter_connections.keys():
                    inverter_data[inverter_name] = await self.hub.async_read_inverter_data(inverter_name)
                _LOGGER.debug("Fetched inverter data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Fetch AC charger data for each AC charger
                ac_charger_data = {}
                for ac_charger_name in self.hub.ac_charger_connections.keys():
                    ac_charger_data[ac_charger_name] = await self.hub.async_read_ac_charger_data(ac_charger_name)
                _LOGGER.debug("Fetched AC charger data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Combine all data
                data = {
                    "plant": plant_data,
                    "inverters": inverter_data,
                    "ac_chargers": ac_charger_data,
                }
                fetched_data = data # Assign to a variable for clarity

                _LOGGER.debug("Fetched all data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # --- Update Integration Sensors ---
                now = dt_util.utcnow()
                _LOGGER.debug("Starting integration sensor updates at %s for %d sensors", now, len(self.integration_sensors))
                for sensor in self.integration_sensors:
                    # Ensure source_entity_id is correctly set on the sensor object
                    if not hasattr(sensor, '_source_entity_id') or not sensor._source_entity_id:
                         _LOGGER.warning("Integration sensor %s is missing source_entity_id attribute.", sensor.entity_id)
                         continue

                    source_entity_id = sensor._source_entity_id # Access the protected attribute
                    _LOGGER.debug("Updating integration sensor %s with source entity ID %s", sensor.entity_id, source_entity_id)

                    # Get the state of the source entity directly from Home Assistant
                    source_state = self.hass.states.get(source_entity_id)
                    current_value = None
                    if source_state and source_state.state not in ["unknown", "unavailable"]:
                        current_value = source_state.state
                    else:
                        _LOGGER.debug("Source entity %s state is %s, skipping integration update for %s",
                                      source_entity_id, source_state.state if source_state else 'None', sensor.entity_id)


                    if current_value is not None:
                        try:
                            # Convert to Decimal, handle potential errors
                            current_value_decimal = Decimal(str(current_value))
                            # Convert power from kW (as fetched/calculated) to W for integration
                            # Assuming source values are in kW based on calculated sensors
                            current_value_watts = current_value_decimal * Decimal(1000)
                            await sensor.async_update_integration(current_value_watts, now)
                            _LOGGER.debug("Successfully updated integration sensor %s", sensor.entity_id)
                        except (InvalidOperation, TypeError, ValueError) as e:
                            _LOGGER.warning("Could not update integration sensor %s: Invalid source value '%s' (%s)",
                                            sensor.entity_id, current_value, e)
                        except Exception as e:
                            _LOGGER.error("Error updating integration sensor %s: %s", sensor.entity_id, e, exc_info=True)
                    else:
                        _LOGGER.debug("Skipping integration update for %s: Source value not found or invalid in fetched data for ID %s.",
                                      sensor.entity_id, source_entity_id)
                _LOGGER.debug("Finished integration sensor updates.")
                # --- End Integration Sensor Update ---


                return fetched_data
        except asyncio.TimeoutError as exception:
            raise UpdateFailed("Timeout communicating with Sigenergy system") from exception
        except Exception as exception:
            raise UpdateFailed(f"Error communicating with Sigenergy system: {exception}") from exception