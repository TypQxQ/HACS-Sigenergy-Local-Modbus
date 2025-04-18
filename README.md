# Sigenergy ESS Integration for Home Assistant

This integration allows you to monitor and control your Sigenergy ESS (Energy Storage System) through Home Assistant. It dynamically discovers and configures your plant, inverters, AC chargers, and DC chargers, providing real-time data and control capabilities.

## Highly experimental
This implementation is still under development and should not be used if you need help.
It is published for those that can help with finding out what works and what doesn't.

## Features

- **Dynamic Device Addition and Configuration:** Easily add and configure multiple inverters, AC chargers, and DC chargers within a single plant configuration.
- **Automatic Device Support Detection:** Utilizes Modbus register probing to automatically determine supported features and entities for your specific Sigenergy devices.
- **Real-time Monitoring:** Monitor power flows (grid import/export, battery charge/discharge, PV production), energy statistics (daily/monthly/yearly counters), and battery metrics (SoC, SoH, temperature, cycles).
- **Inverter and Charger Status:** Track the status of your inverters and chargers, including running state, alarms, and detailed parameters.
- **Control Capabilities:** Control your Sigenergy system with options like starting/stopping the plant, changing EMS work modes, and adjusting power limits (availability depends on device model and configuration).

## Requirements

- Home Assistant 2024.4.1 or newer
- Sigenergy ESS with Modbus TCP access activated by your installer.
- Network connectivity between Home Assistant
- The Home Assistant Community Store (HACS)

## Installation

### HACS Installation (Recommended)

1.  Make sure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.
2.  Add this repository as a custom repository in HACS:
    -   Go to HACS > Integrations
    -   Click the three dots in the top right corner
    -   Select "Custom repositories"
    -   Add the URL of this repository:
    <br>`https://github.com/TypQxQ/HACS-Sigenergy-Local-Modbus`
    -   Select "Integration" as the category
3.  Click "Install" on the Sigenergy integration card.
4.  Restart Home Assistant.

### Manual Installation

1.  Download the latest release from the GitHub repository.
2.  Create a `custom_components/sigen` directory in your Home Assistant configuration directory.
3.  Extract the contents of the release into the `custom_components/sigen` directory.
4.  Restart Home Assistant.

## Configuration

The integration uses a configuration process through the Home Assistant UI.  When adding your first Sigenergy device, the integration will always add a Plant and an Inverter. A Plant represents your overall Sigenergy system, encompassing all connected devices.

To add more devices, you need to add the "Sigenergy" integration again for each subsequent device (Inverter, AC Charger, or DC Charger).

Follow the configuration flow:

1.  Go to Settings > Devices & Services.
2.  Click "Add Integration".
3.  Search for "Sigenergy".
4.  Follow the configuration flow:

    -   **Add a Plant and Inverter:** The first time you add the Sigenergy integration, you will add a "Plant" and the main or only "Inverter". You'll need to provide the host (IP address) and port (default: 502) of your Sigenergy system, and the slave ID (default: 1) for your Inverter. You can also set the integration to read-only mode.
    -   **Adding Subsequent Devices:** To add more devices (Inverters, AC Chargers, DC Chargers), repeat steps 1-3, selecting the "Sigenergy" integration again for each device.
        -   **Inverters:** Provide a host and slave ID for each additional inverter.
        -   **AC Chargers:**  Provide a host and slave ID for each AC charger.
        -   **DC Chargers:** DC Chargers are associated with a specific inverter. You'll select the inverter and the integration will use the inverter's host and slave ID for the DC charger.
### Configuration Parameters

-   **`host`:** The IP address of your Sigenergy system (required for plant and optionally for individual devices).
-   **`port`:** The Modbus TCP port (default: 502, required for plant and optionally for individual devices).
-   **`inverter_slave_ids`:** A list of slave IDs for your inverters.
-   **`ac_charger_slave_ids`:** A list of slave IDs for your AC chargers.
-   **`dc_charger_slave_ids`:** A list of slave IDs for your DC chargers (these correspond to inverter slave IDs).
-   **`inverter_connections`:** A dictionary mapping inverter names to their connection details (host, port, slave ID).
-   **`ac_charger_connections`:** A dictionary mapping AC charger names to their connection details (host, port, slave ID).
-   **`read_only`:**  Set to `True` to prevent the integration from writing to Modbus registers (recommended for initial setup).

## Entities

The integration dynamically creates entities based on the configured devices (plant, inverters, AC chargers, and DC chargers) and the Modbus registers supported by those devices.

**Common Plant Entities:**

-   Plant Active Power
-   Plant Reactive Power
-   Photovoltaic Power
-   Battery State of Charge (SoC)
-   Battery Power (charging/discharging)
-   Grid Active Power (import/export)
-   EMS Work Mode
-   Plant Running State

**Common Inverter Entities:**

-   Active Power
-   Reactive Power
-   Battery Power
-   Battery SoC
-   Battery Temperature
-   PV Power
-   Grid Frequency
-   Phase Voltages
-   Phase Currents
-   Daily Charge/Discharge Energy

**Common AC Charger Entities:**

-   System State
-   Charging Power
-   Total Energy Consumed

**Common DC Charger Entities:** (These will typically be associated with the corresponding inverter entities)

- DC Charger Power
- DC Charger Status

*Note: The specific entities available will depend on your Sigenergy device models and the Modbus registers they support. The integration uses register probing to automatically discover supported entities.*

## Controls

The integration provides control capabilities, allowing you to manage your Sigenergy system. Common control options include:

-   **Plant Power:** Start/stop the plant.
-   **EMS Work Mode:** Select the desired EMS operating mode (e.g., Max Self Consumption, AI Mode, TOU, Remote EMS).

*Note: More advanced controls are available through Home Assistant's Modbus services. The available controls depend on your device model and configuration.*

## Troubleshooting

### Connection Issues

-   Ensure the IP address and port are correct.
-   Check that the Sigenergy system is powered on and connected to the network.
-   Verify that there are no firewalls blocking the connection.
-   Check the Home Assistant logs for detailed error messages.

### Entity Issues

-   If entities are showing as unavailable, check the connection to the Sigenergy system.
-   If values seem incorrect, verify the Modbus slave IDs are configured correctly.
-   For missing entities, ensure that you have added the corresponding devices (inverters, chargers) during the configuration flow. The integration uses dynamic register probing, so it may take some time to discover all supported entities.

## System Compatibility

This integration has been tested with the following Sigenergy models:

-   SigenStorEC series
-   SigenHybrid series
-   SigenPV series
-   Sigen EV DC Charging Module
-   Sigen EV AC Charger

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This integration is licensed under the MIT License.