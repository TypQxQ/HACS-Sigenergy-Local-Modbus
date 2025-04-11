"""Modbus communication for Sigenergy ESS."""
from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple, Union
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry  # pylint: disable=no-name-in-module, syntax-error
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.exceptions import ConnectionException, ModbusException
from pymodbus.payload import BinaryPayloadBuilder
from pymodbus.client.mixin import ModbusClientMixin

from .const import ModbusRegisterDefinition
from .const import (
    CONF_DC_CHARGER_CONNECTIONS,
    CONF_INVERTER_CONNECTIONS,
    CONF_AC_CHARGER_CONNECTIONS,
    CONF_PLANT_ID,
    CONF_SLAVE_ID,
    DEFAULT_PLANT_SLAVE_ID,
    DataType,
    PLANT_RUNNING_INFO_REGISTERS,
    PLANT_PARAMETER_REGISTERS,
    INVERTER_RUNNING_INFO_REGISTERS,
    INVERTER_PARAMETER_REGISTERS,
    AC_CHARGER_RUNNING_INFO_REGISTERS,
    AC_CHARGER_PARAMETER_REGISTERS,
    DC_CHARGER_RUNNING_INFO_REGISTERS,
    DC_CHARGER_PARAMETER_REGISTERS,
    RegisterType,
    DEFAULT_READ_ONLY,
    CONF_READ_ONLY,
    CONF_PLANT_CONNECTION,
)

_LOGGER = logging.getLogger(__name__)

@dataclass
class ModbusConnectionConfig:
    """Configuration for a Modbus connection."""
    name: str
    host: str
    port: int
    slave_id: int


@contextmanager
def _suppress_pymodbus_logging():
    """Temporarily suppress pymodbus logging."""
    pymodbus_logger = logging.getLogger("pymodbus")
    original_level = pymodbus_logger.level
    original_propagate = pymodbus_logger.propagate
    pymodbus_logger.setLevel(logging.CRITICAL)
    pymodbus_logger.propagate = False
    try:
        yield
    finally:
        pymodbus_logger.setLevel(original_level)
        pymodbus_logger.propagate = original_propagate

class SigenergyModbusError(HomeAssistantError):
    """Exception for Sigenergy Modbus errors."""


class SigenergyModbusHub:
    """Modbus hub for Sigenergy ESS."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the Modbus hub."""
        self.hass = hass
        self.config_entry = config_entry
        
        # Dictionary to store Modbus clients for different connections
        # Key is (host, port) tuple, value is the client instance
        self._clients: Dict[Tuple[str, int], AsyncModbusTcpClient] = {}
        self._locks: Dict[Tuple[str, int], asyncio.Lock] = {}
        self._connected: Dict[Tuple[str, int], bool] = {}
        
        # Store connection for plant
        self.plant_connection = config_entry.data.get(CONF_PLANT_CONNECTION, {})
        self._plant_host = self.plant_connection[CONF_HOST]
        self._plant_port = self.plant_connection[CONF_PORT]
        self.plant_id = self.plant_connection.get(CONF_PLANT_ID, DEFAULT_PLANT_SLAVE_ID)

        # Get inverter connections
        self.inverter_connections = config_entry.data.get(CONF_INVERTER_CONNECTIONS, {})
        _LOGGER.debug("Inverter connections: %s", self.inverter_connections)
        self.inverter_count = len(self.inverter_connections)

        # Get AC Charger connections
        self.ac_charger_connections = config_entry.data.get(CONF_AC_CHARGER_CONNECTIONS, {})
        _LOGGER.debug("AC Charger connections: %s", self.ac_charger_connections)
        self.ac_charger_count = len(self.ac_charger_connections)

        # Other slave IDs and their connection details

        # Read-only mode setting
        self.read_only = config_entry.data.get(CONF_READ_ONLY, DEFAULT_READ_ONLY)

        # Initialize register support status
        self.plant_registers_probed = False
        self.inverter_registers_probed = set()
        self.ac_charger_registers_probed = set()
        self.dc_charger_registers_probed = set()

    def _get_connection_key(self, slave_id: int) -> Tuple[str, int]:
        """Get the connection key (host, port) for a slave ID."""
        # For the plant, use the plant's connection details
        if slave_id == self.plant_id:
            return (self._plant_host, self._plant_port)

        # For inverters, look up their connection details
        for name, details in self.inverter_connections.items():
            if details.get(CONF_SLAVE_ID) == slave_id:
                return (details[CONF_HOST], details[CONF_PORT])

        # For AC chargers, look up their connection details
        for name, details in self.ac_charger_connections.items():
            if details.get(CONF_SLAVE_ID) == slave_id:
                return (details[CONF_HOST], details[CONF_PORT])

        # If no specific connection found, use the plant's connection details as default
        return (self._plant_host, self._plant_port)

    async def _get_client(self, slave_id: int) -> AsyncModbusTcpClient:
        """Get or create a Modbus client for the given slave ID."""
        key = self._get_connection_key(slave_id)

        if key not in self._clients or not self._connected.get(key, False):
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()

            async with self._locks[key]:
                if key not in self._clients or not self._connected.get(key, False):
                    host, port = key
                    self._clients[key] = AsyncModbusTcpClient(
                        host=host,
                        port=port,
                        timeout=10,
                        retries=3
                    )

                    connected = await self._clients[key].connect()
                    if not connected:
                        raise SigenergyModbusError(f"Failed to connect to {host}:{port}")

                    self._connected[key] = True
                    _LOGGER.info("Connected to Sigenergy system at %s:%s", host, port)

        return self._clients[key]
    async def async_connect(self, slave_id: Optional[int] = None) -> None:
        """Connect to the Modbus device.
        
        If slave_id is provided, connects to that specific device.
        If slave_id is None, connects to the plant (default device).
        """
        # Cast to help type checker and ensure we always have an int
        actual_slave_id: int = self.plant_id if slave_id is None else slave_id

        key = self._get_connection_key(actual_slave_id)
        await self._get_client(actual_slave_id)

        if not self._connected.get(key, False):
            host, port = key
            raise SigenergyModbusError(
                f"Failed to establish connection to device {actual_slave_id} at {host}:{port}"
            )

    async def async_close(self) -> None:
        """Close all Modbus connections."""
        for key, client in self._clients.items():
            if client and self._connected.get(key, False):
                host, port = key
                async with self._locks[key]:
                    client.close()
                    self._connected[key] = False
                    _LOGGER.info("Disconnected from Sigenergy system at %s:%s", host, port)
    
    def _validate_register_response(self, result: Any, register_def: ModbusRegisterDefinition) -> bool:
        """Validate if register response indicates support for the register."""
        # Handle error responses silently - these indicate unsupported registers
        if result is None or (hasattr(result, 'isError') and result.isError()):
            _LOGGER.debug(f"Register validation failed for address {register_def.address} with error: %s", result)
            return False
            
        registers = getattr(result, 'registers', [])
        if not registers:
            _LOGGER.debug(f"Register validation failed for address {register_def.address}: empty response")
            return False
            
        # For string type registers, check if all values are 0 (indicating no support)
        if register_def.data_type == DataType.STRING:
            _LOGGER.debug(f"Register validation failed for address {register_def.address}: string type (not all string registers have to be filled)")
            return not all(reg == 0 for reg in registers)
            
        # For numeric registers, check if values are within reasonable bounds
        try:
            value = self._decode_value(registers, register_def.data_type, register_def.gain)
            if isinstance(value, (int, float)):
                # Consider register supported if value is non-zero and within reasonable bounds
                # This helps filter out invalid/unsupported registers that might return garbage values
                max_reasonable = {
                    "voltage": 1000,  # 1000V
                    "current": 1000,  # 1000A
                    "power": 100,     # 100kW
                    "energy": 100000, # 100MWh
                    "temperature": 100, # 100°C
                    "percentage": 120  # 120% Some batteries can go above 100% when charging
                }
                
                # Determine max value based on unit if present
                if register_def.unit:
                    unit = register_def.unit.lower()
                    if any(u in unit for u in ["v", "volt"]):
                        return 0 <= abs(value) <= max_reasonable["voltage"]
                    elif any(u in unit for u in ["a", "amp"]):
                        return 0 <= abs(value) <= max_reasonable["current"]
                    elif any(u in unit for u in ["w", "watt"]):
                        return 0 <= abs(value) <= max_reasonable["power"]
                    elif any(u in unit for u in ["wh", "kwh"]):
                        return 0 <= abs(value) <= max_reasonable["energy"]
                    elif any(u in unit for u in ["c", "f", "temp"]):
                        return -50 <= value <= max_reasonable["temperature"]
                    elif "%" in unit:
                        return 0 <= value <= max_reasonable["percentage"]
                # Default validation - accept any value including 0
                return True
            
            return True
        except Exception as ex:
            _LOGGER.debug("Register validation failed with exception: %s", ex)
            return False
            
    async def async_probe_registers(
        self,
        device_info: Dict[str, str | int],
        register_defs: Dict[str, ModbusRegisterDefinition]
    ) -> None:
        """Probe registers to determine which ones are supported."""
        slave_id_value = device_info.get(CONF_SLAVE_ID)
        if slave_id_value is None:
            raise ValueError(f"Slave ID is missing in device info: {device_info}")
        slave_id = int(slave_id_value)
        client = await self._get_client(slave_id)
        key = self._get_connection_key(slave_id)
            
        for name, register in register_defs.items():
            try:
                # Get raw result from appropriate read method
                async with self._locks[key]:
                    with _suppress_pymodbus_logging():
                        if register.register_type == RegisterType.READ_ONLY:
                            result = await client.read_input_registers(
                                address=register.address,
                                count=register.count,
                                slave=slave_id
                            )
                        elif register.register_type == RegisterType.HOLDING:
                            result = await client.read_holding_registers(
                                address=register.address,
                                count=register.count,
                                slave=slave_id
                            )
                        else:
                            _LOGGER.debug(
                                "Register %s (0x%04X) for slave %d has unsupported type: %s",
                                name,
                                register.address,
                                slave_id,
                                register.register_type
                            )
                            register.is_supported = False
                            continue

                # Validate the response without raising exceptions for expected error cases
                register.is_supported = self._validate_register_response(result, register)
                
                if _LOGGER.isEnabledFor(logging.DEBUG) and not register.is_supported:
                    _LOGGER.debug(
                        "Register %s (%s) for slave %d is not supported. Result: %s, registers: %s",
                        name,
                        register.address,
                        slave_id,
                        str(result),
                        str(register)
                    )
                
            except Exception as ex:
                if _LOGGER.isEnabledFor(logging.DEBUG):
                    _LOGGER.debug(
                        "Register %s (0x%04X) for slave %d is not supported: %s",
                        name,
                        register.address,
                        slave_id,
                        str(ex)
                    )
                register.is_supported = False
                self._connected[key] = False

    async def async_read_registers(
        self,
        device_info: Dict[str, Any], # Changed from slave_id
        address: int,
        count: int,
        register_type: RegisterType
    ) -> Optional[List[int]]:
        """Read registers from the Modbus device."""
        slave_id_value = device_info.get(CONF_SLAVE_ID)
        if slave_id_value is None:
            _LOGGER.error("Slave ID missing in device info for read operation: %s", device_info)
            # Return None as per function signature, indicating read failure
            return None
        slave_id = int(slave_id_value)

        try:
            client = await self._get_client(slave_id)
            key = self._get_connection_key(slave_id)

            async with self._locks[key]:
                with _suppress_pymodbus_logging():
                    result = await client.read_input_registers(
                        address=address, count=count, slave=slave_id
                    ) if register_type == RegisterType.READ_ONLY else await client.read_holding_registers(
                        address=address, count=count, slave=slave_id
                    )
                    
                    if result.isError():
                        self._connected[key] = False
                        return None
                    return result.registers

        except ConnectionException as ex:
            key = self._get_connection_key(slave_id) # slave_id is already extracted
            self._connected[key] = False
            raise SigenergyModbusError(f"Connection error: {ex}") from ex
        except ModbusException as ex:
            raise SigenergyModbusError(f"Modbus error: {ex}") from ex
        except Exception as ex:
            raise SigenergyModbusError(f"Error reading registers: {ex}") from ex

    async def async_write_register(
        self,
        slave_id: int,
        address: int,
        value: int,
        register_type: RegisterType
    ) -> None:
        """Write a single register to the Modbus device."""
        try:
            client = await self._get_client(slave_id)
            key = self._get_connection_key(slave_id)

            async with self._locks[key]:
                if register_type in [RegisterType.HOLDING, RegisterType.WRITE_ONLY]:
                    # Try multiple approaches to write to the register
                    approaches = []
                    
                    # Always try direct addressing approaches
                    approaches.append({
                        "description": f"write_registers with direct addressing ({address})",
                        "function": "write_registers",
                        "address": address,
                        "values": [value]
                    })
                    approaches.append({
                        "description": f"write_register with direct addressing ({address})",
                        "function": "write_register",
                        "address": address,
                        "value": value
                    })
                    
                    # Try each approach until one succeeds
                    last_error = None
                    success = False
                    
                    for i, approach in enumerate(approaches):
                        try:
                            _LOGGER.debug(
                                "Attempt %d: Using %s for register %s with value %s for slave %s",
                                i+1, approach["description"], address, value, slave_id
                            )
                            
                            if approach["function"] == "write_registers":
                                result = await client.write_registers(
                                    address=approach["address"],
                                    values=approach["values"],
                                    slave=slave_id
                                )
                            else:  # write_register
                                result = await client.write_register(
                                    address=approach["address"],
                                    value=approach["value"],
                                    slave=slave_id
                                )
                                
                            if not result.isError():
                                _LOGGER.debug("Success with approach: %s", approach["description"])
                                success = True
                                break
                            
                            _LOGGER.debug("Error with approach %s: %s", approach["description"], result)
                            last_error = result
                            
                        except Exception as ex:
                            _LOGGER.debug("Exception with approach %s: %s", approach["description"], ex)
                            last_error = ex
                    
                    # Check if any approach succeeded
                    if success:
                        _LOGGER.debug("Successfully wrote to register at address %s", address)
                        return
                        
                    # If we've tried all approaches and still have an error
                    self._connected[key] = False
                    if last_error:
                        _LOGGER.debug("All write attempts failed. Final error: %s", last_error)
                        if isinstance(last_error, Exception):
                            # Re-raise the exception
                            raise last_error
                        else:
                            # It's a Modbus error response
                            raise SigenergyModbusError(
                                f"Error writing register at address {address}: {last_error}"
                            )
                else:
                    raise SigenergyModbusError(
                        f"Register type {register_type} is not writable"
                    )
        except ConnectionException as ex:
            key = self._get_connection_key(slave_id)
            self._connected[key] = False
            raise SigenergyModbusError(f"Connection error: {ex}") from ex
        except ModbusException as ex:
            raise SigenergyModbusError(f"Modbus error: {ex}") from ex
        except Exception as ex:
            raise SigenergyModbusError(f"Error writing register: {ex}") from ex

    async def async_write_registers(
        self,
        slave_id: int,
        address: int,
        values: List[int],
        register_type: RegisterType
    ) -> None:
        """Write multiple registers to the Modbus device."""
        try:
            client = await self._get_client(slave_id)
            key = self._get_connection_key(slave_id)

            async with self._locks[key]:
                if register_type in [RegisterType.HOLDING, RegisterType.WRITE_ONLY]:
                    # For Modbus addresses starting with 4xxxx, some devices expect the offset (address - 40001)
                    if address >= 40001:
                        # Try with the offset addressing first
                        offset_address = address - 40001
                        _LOGGER.debug(
                            "Writing to registers starting at %s (offset address %s) with values %s for slave %s",
                            address, offset_address, values, slave_id
                        )
                        result = await client.write_registers(
                            address=offset_address, values=values, slave=slave_id
                        )
                    else:
                        _LOGGER.debug(
                            "Writing to registers starting at %s with values %s for slave %s",
                            address, values, slave_id
                        )
                        result = await client.write_registers(
                            address=address, values=values, slave=slave_id
                        )
                    
                    if result.isError():
                        self._connected[key] = False
                        _LOGGER.debug("Error response from write_registers: %s", result)
                        raise SigenergyModbusError(
                            f"Error writing registers at address {address}: {result}"
                        )
                    else:
                        _LOGGER.debug("Successfully wrote to registers starting at address %s", address)
                else:
                    raise SigenergyModbusError(
                        f"Register type {register_type} is not writable"
                    )
        except ConnectionException as ex:
            key = self._get_connection_key(slave_id)
            self._connected[key] = False
            raise SigenergyModbusError(f"Connection error: {ex}") from ex
        except ModbusException as ex:
            raise SigenergyModbusError(f"Modbus error: {ex}") from ex
        except Exception as ex:
            raise SigenergyModbusError(f"Error writing registers: {ex}") from ex

    def _decode_value(
        self, 
        registers: List[int], 
        data_type: DataType, 
        gain: float
    ) -> Union[int, float, str]:
        """Decode register values based on data type."""
        if data_type == DataType.U16:
            value = ModbusClientMixin.convert_from_registers(
                registers, data_type=ModbusClientMixin.DATATYPE.UINT16
            )
        elif data_type == DataType.S16:
            value = 0
            value = ModbusClientMixin.convert_from_registers(
                registers, data_type=ModbusClientMixin.DATATYPE.INT16
            )
        elif data_type == DataType.U32:
            value = 0
            value = ModbusClientMixin.convert_from_registers(
                registers, data_type=ModbusClientMixin.DATATYPE.UINT32
            )
        elif data_type == DataType.S32:
            value = 0
            value = ModbusClientMixin.convert_from_registers(
                registers, data_type=ModbusClientMixin.DATATYPE.INT32
            )
        elif data_type == DataType.U64:
            value = 0
            value = ModbusClientMixin.convert_from_registers(
                registers, data_type=ModbusClientMixin.DATATYPE.UINT64
            )
        elif data_type == DataType.STRING:
            # return value  # No gain for strings
            return ModbusClientMixin.convert_from_registers(
                registers,
                data_type=ModbusClientMixin.DATATYPE.STRING)  # type: ignore[no-untyped-call]
        else:
            raise SigenergyModbusError(f"Unsupported data type: {data_type}")

        # Apply gain
        if isinstance(value, (int, float)) and gain != 1:
            value = value / gain

        return value  # type: ignore[no-untyped-return]

    def _encode_value(
        self, 
        value: Union[int, float, str], 
        data_type: DataType, 
        gain: float
    ) -> List[int]:
        """Encode value to register values based on data type."""
        # For simple U16 values like 0 or 1, just return the value directly
        # This bypasses potential byte order issues with the BinaryPayloadBuilder
        if data_type == DataType.U16 and isinstance(value, int) and 0 <= value <= 255:
            _LOGGER.debug("Using direct value encoding for simple U16 value: %s", value)
            return [value]
            
        # For other cases, use the BinaryPayloadBuilder
        builder = BinaryPayloadBuilder(byteorder=Endian.BIG, wordorder=Endian.BIG)
        
        # Apply gain for numeric values
        if isinstance(value, (int, float)) and gain != 1 and data_type != DataType.STRING:
            value = int(value * gain)
        
        _LOGGER.debug("Encoding value %s with data_type %s", value, data_type)
        
        if data_type == DataType.U16:
            builder.add_16bit_uint(int(value))
        elif data_type == DataType.S16:
            builder.add_16bit_int(int(value))
        elif data_type == DataType.U32:
            builder.add_32bit_uint(int(value))
        elif data_type == DataType.S32:
            builder.add_32bit_int(int(value))
        elif data_type == DataType.U64:
            builder.add_64bit_uint(int(value))
        elif data_type == DataType.STRING:
            builder.add_string(str(value))
        else:
            raise SigenergyModbusError(f"Unsupported data type: {data_type}")
        
        registers = builder.to_registers()
        _LOGGER.debug("Encoded registers: %s", registers)
        return registers
    
    async def _async_read_device_data_core(
        self,
        device_info: Dict[str, Any], # Changed from slave_id
        device_name: str,
        device_type_log_prefix: str,
        registers_to_read: Dict[str, ModbusRegisterDefinition]
    ) -> Dict[str, Any]:
        """Core logic for reading device data registers."""

        data = {}
        for register_name, register_def in registers_to_read.items():
            if register_def.is_supported is not False:  # Read if supported or unknown
                try:
                    registers = await self.async_read_registers(
                        device_info=device_info,
                        address=register_def.address,
                        count=register_def.count,
                        register_type=register_def.register_type,
                    )

                    if registers is None:
                        data[register_name] = None
                        # If probing failed or wasn't done, and read fails, mark as unsupported
                        if register_def.is_supported is None:
                            register_def.is_supported = False
                        continue

                    value = self._decode_value(
                        registers=registers,
                        data_type=register_def.data_type,
                        gain=register_def.gain,
                    )

                    data[register_name] = value
                    # _LOGGER.debug("Read register %s = %s from %s '%s'", register_name, value, device_type_log_prefix, device_name)

                    # If we successfully read a register that wasn't probed/confirmed, mark it as supported
                    if register_def.is_supported is None:
                        register_def.is_supported = True

                except Exception as ex:
                    _LOGGER.error(
                        "Error reading %s '%s' register %s: %s",
                        device_type_log_prefix, device_name, register_name, ex
                    )
                    data[register_name] = None
                    # If this is the first time we fail to read this register, mark it as unsupported
                    if register_def.is_supported is None:
                        register_def.is_supported = False
        return data

    async def async_read_plant_data(self) -> Dict[str, Any]:
        """Read all supported plant data."""
        # Probe registers if not done yet
        if not self.plant_registers_probed:
            try:
                plant_info = self.config_entry.data.get(CONF_PLANT_CONNECTION, {})
                await self.async_probe_registers(plant_info, PLANT_RUNNING_INFO_REGISTERS)
                # Also probe parameter registers that can be read
                await self.async_probe_registers(plant_info, {
                    name: reg for name, reg in PLANT_PARAMETER_REGISTERS.items()
                    if reg.register_type != RegisterType.WRITE_ONLY
                })
                self.plant_registers_probed = True
            except Exception as ex:
                _LOGGER.error("Failed to probe plant registers: %s", ex)
                # Continue with reading, some registers might still work
        
        # Read registers from both running info and parameter registers
        all_registers = {
            **PLANT_RUNNING_INFO_REGISTERS,
            **{name: reg for name, reg in PLANT_PARAMETER_REGISTERS.items()
               if reg.register_type != RegisterType.WRITE_ONLY}
        }
        
        # Use the core reading logic
        plant_info = self.config_entry.data.get(CONF_PLANT_CONNECTION, {}) # Ensure plant_info is available
        plant_info.setdefault(CONF_SLAVE_ID, self.plant_id) # Ensure slave_id is in plant_info
        return await self._async_read_device_data_core(
            device_info=plant_info,
            device_name="plant",
            device_type_log_prefix="plant",
            registers_to_read=all_registers
        )

    async def async_read_inverter_data(self, inverter_name: str) -> Dict[str, Any]:
        """Read all supported inverter data."""
        # Look up inverter details by name
        if inverter_name not in self.inverter_connections:
            _LOGGER.error("Unknown inverter name provided for reading data: %s", inverter_name)
            return {} # Return empty dict if inverter name is not found
        inverter_info = self.inverter_connections[inverter_name]

        # Probe registers if not done yet for this inverter
        if inverter_name not in self.inverter_registers_probed:
            try:
                await self.async_probe_registers(inverter_info, INVERTER_RUNNING_INFO_REGISTERS)
                # Also probe parameter registers that can be read
                await self.async_probe_registers(inverter_info, {
                    name: reg for name, reg in INVERTER_PARAMETER_REGISTERS.items()
                    if reg.register_type != RegisterType.WRITE_ONLY
                })
                self.inverter_registers_probed.add(inverter_name)
            except Exception as ex:
                _LOGGER.error("Failed to probe inverter '%s' registers: %s", inverter_name, ex)
                # Continue with reading, some registers might still work

        # Read registers from both running info and parameter registers
        all_registers = {
            **INVERTER_RUNNING_INFO_REGISTERS,
            **{name: reg for name, reg in INVERTER_PARAMETER_REGISTERS.items()
            if reg.register_type != RegisterType.WRITE_ONLY},
            **DC_CHARGER_RUNNING_INFO_REGISTERS,
            **{name: reg for name, reg in DC_CHARGER_PARAMETER_REGISTERS.items()
            if reg.register_type != RegisterType.WRITE_ONLY},
        }

        # Use the core reading logic
        return await self._async_read_device_data_core(
            device_info=inverter_info,
            device_name=inverter_name,
            device_type_log_prefix="inverter",
            registers_to_read=all_registers
        )

    async def async_read_ac_charger_data(self, ac_charger_name: str) -> Dict[str, Any]:
        """Read all supported AC charger data."""
        # Look up AC charger details by name
        if ac_charger_name not in self.ac_charger_connections:
            _LOGGER.error("Unknown AC charger name provided for reading data: %s", ac_charger_name)
            return {}  # Return empty dict if AC charger name is not found

        ac_charger_info = self.ac_charger_connections[ac_charger_name]

        # Probe registers if not done yet for this AC charger
        if ac_charger_name not in self.ac_charger_registers_probed:
            try:
                await self.async_probe_registers(ac_charger_info, AC_CHARGER_RUNNING_INFO_REGISTERS)
                # Also probe parameter registers that can be read
                await self.async_probe_registers(ac_charger_info, {
                    name: reg for name, reg in AC_CHARGER_PARAMETER_REGISTERS.items()
                    if reg.register_type != RegisterType.WRITE_ONLY
                })
                self.ac_charger_registers_probed.add(ac_charger_name)
            except Exception as ex:
                _LOGGER.error("Failed to probe AC charger '%s' registers: %s", ac_charger_name, ex)
                # Continue with reading, some registers might still work

        # Read registers from both running info and parameter registers
        all_registers = {
            **AC_CHARGER_RUNNING_INFO_REGISTERS,
            **{name: reg for name, reg in AC_CHARGER_PARAMETER_REGISTERS.items()
               if reg.register_type != RegisterType.WRITE_ONLY}
        }

        # Use the core reading logic
        return await self._async_read_device_data_core(
            device_info=ac_charger_info,
            device_name=ac_charger_name,
            device_type_log_prefix="AC charger",
            registers_to_read=all_registers
        )

    async def async_write_parameter(
        self,
        device_type: str,
        device_identifier: Optional[str],
        register_name: str,
        value: Union[int, float, str]
    ) -> None:
        """Write a parameter to a specified device (plant, inverter, or AC charger).

        Args:
            device_type: The type of device ('plant', 'inverter', 'ac_charger').
            device_identifier: The name of the inverter or AC charger, or None for the plant.
            register_name: The name of the parameter register to write.
            value: The value to write to the register.

        Raises:
            SigenergyModbusError: If writing is disabled (read-only mode), the device/parameter
                                  is unknown, slave ID is missing, or a Modbus error occurs.
            ValueError: If device_type is invalid or device_identifier is missing when required.
        """
        if self.read_only:
            raise SigenergyModbusError("Cannot write parameter while in read-only mode")

        slave_id: Optional[int] = None
        parameter_registers: Dict[str, ModbusRegisterDefinition] = {}
        connection_dict: Optional[Dict] = None # To store inverter_connections or ac_charger_connections

        # Determine slave ID and parameter dictionary based on device type
        if device_type == "plant":
            connection_dict = self.plant_connection
            parameter_registers = PLANT_PARAMETER_REGISTERS
        elif device_type == "inverter":
            if not device_identifier:
                raise ValueError("device_identifier is required for device_type 'inverter'")
            connection_dict = self.inverter_connections
            parameter_registers = INVERTER_PARAMETER_REGISTERS
        elif device_type == "ac_charger":
            if not device_identifier:
                raise ValueError("device_identifier is required for device_type 'ac_charger'")
            connection_dict = self.ac_charger_connections
            parameter_registers = AC_CHARGER_PARAMETER_REGISTERS
        else:
            raise ValueError(f"Unknown device_type: {device_type}")

        # Get slave_id for inverter/ac_charger from connection details
        if connection_dict is not None and device_identifier:
            if device_identifier not in connection_dict:
                raise SigenergyModbusError(f"Unknown {device_type} name: {device_identifier}")
            device_info = connection_dict[device_identifier]
            slave_id = device_info.get(CONF_SLAVE_ID)
            if slave_id is None:
                raise SigenergyModbusError(f"Slave ID not configured for {device_type}: {device_identifier}")

        # Safety check: Ensure slave_id was determined
        if slave_id is None:
             raise SigenergyModbusError(f"Could not determine slave ID for {device_type} '{device_identifier}'")

        # Get register definition
        if register_name not in parameter_registers:
            raise SigenergyModbusError(f"Unknown {device_type} parameter: {register_name}")
        register_def = parameter_registers[register_name]

        _LOGGER.debug(
            "Writing %s parameter '%s' (device: %s) with value %s to address %s (type: %s, data_type: %s, gain: %s)",
            device_type, register_name, device_identifier or 'plant', value, register_def.address,
            register_def.register_type, register_def.data_type, register_def.gain
        )

        # === Plant-Specific Handling ===
        # Certain plant registers require special handling due to Modbus quirks
        if device_type == "plant":
            key = self._get_connection_key(slave_id) # Get connection key for client/lock

            # Special handling for plant_remote_ems_enable register
            if register_name == "plant_remote_ems_enable":
                _LOGGER.debug("Special handling for plant_remote_ems_enable register")
                approaches = [
                    {"function": "write_registers", "address": register_def.address, "values": [int(value)]},
                    {"function": "write_register", "address": register_def.address, "value": int(value)},
                    {"function": "write_registers", "address": register_def.address - 40001, "values": [int(value)]},
                    {"function": "write_register", "address": register_def.address - 40001, "value": int(value)},
                ]
                last_error = None
                success = False
                try:
                    client = await self._get_client(slave_id) # Ensure client is ready
                    async with self._locks[key]:
                        for i, approach in enumerate(approaches):
                            try:
                                _LOGGER.debug(
                                    "Attempt %d for plant_remote_ems_enable: Using %s with address %s and value %s",
                                    i+1, approach["function"], approach["address"],
                                    approach.get("value", approach.get("values"))
                                )
                                if approach["function"] == "write_registers":
                                    result = await client.write_registers(
                                        address=approach["address"], values=approach["values"], slave=slave_id
                                    )
                                else: # write_register
                                    result = await client.write_register(
                                        address=approach["address"], value=approach["value"], slave=slave_id
                                    )

                                if not hasattr(result, 'isError') or not result.isError():
                                    _LOGGER.debug("Success with approach %d for plant_remote_ems_enable", i+1)
                                    success = True
                                    break # Success, exit loop

                                _LOGGER.debug("Error with approach %d: %s", i+1, result)
                                last_error = result
                            except Exception as ex_inner: # Catch errors within the loop
                                _LOGGER.debug("Exception with approach %d: %s", i+1, ex_inner)
                                last_error = ex_inner
                                # Continue to next approach

                    if success:
                        return # Exit method after successful special handling

                    # If loop finished without success
                    if isinstance(last_error, Exception):
                        raise SigenergyModbusError(f"Error writing plant_remote_ems_enable after multiple attempts: {last_error}") from last_error
                    else:
                        raise SigenergyModbusError(f"Error writing plant_remote_ems_enable after multiple attempts: {last_error}")

                except (ConnectionException, ModbusException, SigenergyModbusError) as ex_outer:
                    self._connected[key] = False # Mark connection as potentially broken
                    raise ex_outer # Re-raise known Modbus/Connection errors
                except Exception as ex_outer: # Catch unexpected errors during client/lock handling
                    self._connected[key] = False
                    raise SigenergyModbusError(f"Unexpected error writing plant_remote_ems_enable: {ex_outer}") from ex_outer


            # Special handling for U32/S32 registers
            elif register_def.data_type in [DataType.U32, DataType.S32]:
                _LOGGER.debug("Special handling for U32/S32 register %s", register_name)
                encoded_values = self._encode_value(value=value, data_type=register_def.data_type, gain=register_def.gain)
                _LOGGER.debug("Encoded values for %s: %s", register_name, encoded_values)
                approaches = [
                    {"address": register_def.address},
                    {"address": register_def.address - 40001},
                    {"address": register_def.address - 40000},
                    {"address": register_def.address % 10000},
                ]
                last_error = None
                success = False
                try:
                    client = await self._get_client(slave_id) # Ensure client is ready
                    async with self._locks[key]:
                        for i, approach in enumerate(approaches):
                            # Skip invalid addresses
                            if approach["address"] < 0:
                                _LOGGER.debug("Skipping attempt %d for %s: Invalid address %s", i+1, register_name, approach["address"])
                                continue
                            try:
                                _LOGGER.debug(
                                    "Attempt %d for %s: Using address %s with values %s",
                                    i+1, register_name, approach["address"], encoded_values
                                )
                                result = await client.write_registers(
                                    address=approach["address"], values=encoded_values, slave=slave_id
                                )

                                if not result.isError():
                                    _LOGGER.debug("Success with approach %d for %s at address %s",
                                                i+1, register_name, approach["address"])
                                    success = True
                                    break # Success, exit loop

                                _LOGGER.debug("Error with approach %d: %s", i+1, result)
                                last_error = result
                            except Exception as ex_inner: # Catch errors within the loop
                                _LOGGER.debug("Exception with approach %d: %s", i+1, ex_inner)
                                last_error = ex_inner
                                # Continue to next approach

                    if success:
                        return # Exit method after successful special handling

                    # If loop finished without success
                    if isinstance(last_error, Exception):
                         raise SigenergyModbusError(f"Error writing {register_name} after multiple attempts: {last_error}") from last_error
                    else:
                         raise SigenergyModbusError(f"Error writing {register_name} after multiple attempts: {last_error}")

                except (ConnectionException, ModbusException, SigenergyModbusError) as ex_outer:
                    self._connected[key] = False # Mark connection as potentially broken
                    raise ex_outer # Re-raise known Modbus/Connection errors
                except Exception as ex_outer: # Catch unexpected errors during client/lock handling
                    self._connected[key] = False
                    raise SigenergyModbusError(f"Unexpected error writing {register_name}: {ex_outer}") from ex_outer

        # === General Write Logic ===
        # (Executes if device_type is not 'plant' or if it's a plant register without special handling)
        encoded_values = self._encode_value(
            value=value,
            data_type=register_def.data_type,
            gain=register_def.gain,
        )
        _LOGGER.debug("Encoded values for %s '%s': %s", device_type, register_name, encoded_values)

        # Use the existing high-level write methods which handle locks/clients internally
        try:
            if len(encoded_values) == 1:
                await self.async_write_register(
                    slave_id=slave_id,
                    address=register_def.address,
                    value=encoded_values[0],
                    register_type=register_def.register_type,
                )
            else:
                await self.async_write_registers(
                    slave_id=slave_id,
                    address=register_def.address,
                    values=encoded_values,
                    register_type=register_def.register_type,
                )
        except SigenergyModbusError as ex:
            _LOGGER.error("Failed to write %s parameter '%s' (device: %s): %s",
                          device_type, register_name, device_identifier or 'plant', ex)
            raise # Re-raise the specific error
