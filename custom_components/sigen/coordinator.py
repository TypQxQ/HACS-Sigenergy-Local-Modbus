"""Data update coordinator for Sigenergy ESS."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any, Dict

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed  # pylint: disable=syntax-error
from homeassistant.util import dt as dt_util

from .modbus import SigenergyModbusHub

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
        self.platforms = []
        self.largest_update_interval : float = 0.0

        super().__init__(
            hass,
            logger,
            name=name,
            update_interval= update_interval,
        )

    async def _async_update_data(self) -> Dict[str, Any]:
        """Update data via Modbus library."""
        try:
            async with async_timeout.timeout(60):
                update_interval = self.update_interval.total_seconds() if self.update_interval else 5.0
                # _LOGGER.debug("Fetching data from Sigenergy system by Modbus")
                start_time = dt_util.utcnow()

                # Fetch plant data
                plant_data = await self.hub.async_read_plant_data()

                # _LOGGER.debug("Fetched plant data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Fetch inverter data for each inverter
                inverter_data = {}
                for inverter_name in self.hub.inverter_connections.keys():
                    inverter_data[inverter_name] = await self.hub.async_read_inverter_data(inverter_name)
                # _LOGGER.debug("Fetched inverter data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Fetch AC charger data for each AC charger
                ac_charger_data = {}
                for ac_charger_name in self.hub.ac_charger_connections.keys():
                    ac_charger_data[ac_charger_name] = await self.hub.async_read_ac_charger_data(ac_charger_name)
                # _LOGGER.debug("Fetched AC charger data in %s seconds", (dt_util.utcnow() - start_time).total_seconds())

                # Combine all data
                data = {
                    "plant": plant_data,
                    "inverters": inverter_data,
                    "ac_chargers": ac_charger_data,
                }

                timetaken = (dt_util.utcnow() - start_time).total_seconds()
                # First time is much slower than subsequent times
                if self.largest_update_interval == 0.0:
                    self.largest_update_interval = 0.1
                    _LOGGER.debug("First update interval: %s seconds", timetaken)
                elif timetaken > update_interval:
                    self.largest_update_interval = update_interval
                    _LOGGER.warning("Fetching Sigenergy Modbus data took %s seconds which is larger than the update interval.", timetaken)
                elif self.largest_update_interval < timetaken:
                    self.largest_update_interval = timetaken
                    _LOGGER.debug("Largest update interval so far: %s seconds", self.largest_update_interval)
                # else:
                #     _LOGGER.debug("Fetching data took %s seconds", timetaken)

                return data
        except asyncio.TimeoutError as exception:
            raise UpdateFailed("Timeout communicating with Sigenergy system") from exception
        except Exception as exception:
            raise UpdateFailed(f"Error communicating with Sigenergy system: {exception}") from exception