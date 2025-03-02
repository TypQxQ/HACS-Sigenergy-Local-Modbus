"""Diagnostics support for Sigenergy ESS."""
# pylint: disable=import-error
# pyright: reportMissingImports=false
from __future__ import annotations

from typing import Any, Dict

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_HOST, CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> Dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    hub = hass.data[DOMAIN][entry.entry_id]["hub"]

    diagnostics_data = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "data": coordinator.data,
        "hub_info": {
            "host": "redacted",
            "port": hub.port,
            "plant_id": hub.plant_id,
            "inverter_count": hub.inverter_count,
            "ac_charger_count": hub.ac_charger_count,
            "inverter_slave_ids": hub.inverter_slave_ids,
            "ac_charger_slave_ids": hub.ac_charger_slave_ids,
            "connected": hub.connected,
        },
    }

    return diagnostics_data