# Nagios Plugins Collection

My personal nagios plugins, suited for my environment

![Nagios Plugins](pics/rVuPqNb.png)

## Overview

These plugins are tested only by me using them in my own environment

## Available Plugins

- check_gmodem2 - Telekom Glasfasermodem 2 fiber optic modem monitoring
- check_p110 - TP-Link P110 smart plug monitoring with KLAP protocol
- check_jetdirect - Network printer monitoring via SNMP
- check_goss - Infrastructure validation using Goss framework
- check_compose - Docker Compose service health monitoring
- check_eap772 - TP-Link Omada EAP772 access point monitoring via SNMPv3
- check_kindle - Kindle device monitoring via custom management platform API
- check_smart - SMART drive health monitoring for ATA/SCSI/NVMe devices
- check_lm_sensors - Hardware sensor monitoring (temperature, fans, voltages) and HDD temperatures
- check_space_usage - Disk space usage analysis by directory (respects mount points, excludes network mounts)
- check_lpr - LPD/LPR printer daemon protocol testing (RFC 1179)

For detailed plugin documentation see [README-CHECKS.md](README-CHECKS.md)

## TAPO KLAP Problems

**Important:** Starting from firmware version 1.4 (released November 2025), you must enable **Third-party Vendor Compatibility** in the Tapo app settings to use the KLAP protocol with the P110 smart plug. Without this setting enabled, the plugin will not be able to communicate with the device.

To enable third-party vendor compatibility:

1. Open the Tapo app and select your P110 device
   
   <img src="pics/tapo_1.jpeg" alt="Tapo App Device Selection" width="300">

2. Navigate to device settings
   
   <img src="pics/tapo_2.jpeg" alt="Tapo Device Settings" width="300">

3. Enable "Third-party Vendor Compatibility"
   
   <img src="pics/tapo_3.jpeg" alt="Enable Third-party Compatibility" width="300">

## Quick Start

### Installation (recommended): prebuilt bundle via Ansible

One self-contained x86_64 bundle (standalone Python 3.12, locked dependencies
from `requirements.txt`, goss) is built once and installed on all hosts. No
uv, venv or compiler is needed on the hosts; it runs on every x86_64 Linux
with glibc 2.28 or newer (EL8+, Debian 10+, Ubuntu 20.04+, SLES 15+).

```bash
cd ansible
ansible-galaxy collection install -r requirements.yml
ansible-playbook -i HOSTS playbook.yml
```

The role (`ansible/roles/deploy-nagios-plugins-custom`):

- installs smartmontools, lm-sensors, net-snmp tools and setcap
- downloads `nagios-plugins-custom-<version>-x86_64.tar.gz` from the GitHub
  release, checks its SHA-256 and unpacks it to `/opt/nagios-plugins-custom-<version>`
- points `/opt/nagios-plugins-lukas` (the path used by the CheckCommands) to
  it; an old git checkout there is moved to `/opt/nagios-plugins-lukas.pre-<version>`
- creates `python3-lpr` (system python with `cap_net_bind_service`) for
  `check_lpr`
- writes `/etc/sudoers.d/nagios-plugins` (smartctl, hddtemp, check_lpr;
  `sensors` needs no root)
- skips hosts that are not x86_64

Verify:

```
sudo -u nagios /opt/nagios-plugins-lukas/check_lm_sensors --version
cat /opt/nagios-plugins-lukas/BUILDINFO
```

### Build and release

```bash
build/build.sh      # dist/nagios-plugins-custom-<version>-x86_64.tar.gz, ~30 s
build/release.sh    # GitHub release v<version>, needs gh auth login
```

The version comes from `pyproject.toml`. Dependencies: edit
`requirements.in`, then lock with the command at its top.

### Legacy installation

`install.sh` (git checkout plus per-host uv venv) still works but is replaced
by the bundle; it pulls unpinned dependencies on every host.

## Architecture

- Python scripts: plugin logic
- Wrapper scripts: run the script with the bundled Python and `lib/`
- Bundle: standalone Python, locked dependencies, goss, built on Rocky Linux 8

## Configuration Examples

### Nagios

Add command definitions to your Nagios configuration:

```
define command {
    command_name    check_gmodem2
    command_line    /opt/nagios-plugins-lukas/check_gmodem2 -H $HOSTADDRESS$ --rx-power-warning -15
}

define command {
    command_name    check_p110
    command_line    /opt/nagios-plugins-lukas/check_p110 -H $HOSTADDRESS$ -u $ARG1$ -p $ARG2$
}

define command {
    command_name    check_kindle
    command_line    /opt/nagios-plugins-lukas/check_kindle -u $ARG1$ -s $ARG2$ --offline-hours $ARG3$
}
```

Then reload the Nagios configuration:

```
sudo systemctl reload nagios
```

### Icinga2

#### Method 1: Manual Configuration

Copy the custom command definitions to your Icinga2 configuration:

```
sudo cp /opt/nagios-plugins-lukas/icinga-custom-commands/commands-custom.conf /etc/icinga2/conf.d/
sudo systemctl reload icinga2
```

Verify the configuration:

```
sudo icinga2 daemon -C
```

#### Method 2: Icinga Director Integration (Recommended)

For environments using Icinga Director, follow these steps to import and configure the custom check commands:

1. **Deploy to Global Zone**

   Copy the command definitions to the global zone on your Icinga master (config endpoint):
   ```
   sudo cp /opt/nagios-plugins-lukas/icinga-custom-commands/commands-custom.conf \
       /etc/icinga2/zones.d/global-templates/
   ```

2. **Import via Director Kickstart Wizard**

   - Navigate to the Director web interface
   - Go to **Icinga Director** → **Icinga Infrastructure** → **Kickstart Wizard**
   - Click **Run Import** to sync the configuration
   - Check the **Activity Log** to verify new commands are staged for deployment
   - Click **Deploy** to push the configuration to your Icinga infrastructure

3. **Create Service Templates**

   - Navigate to **Director** → **Services** → **Service Templates**
   - Click **Add** to create a new service template
   - Select your desired check command (e.g., `check_gmodem2`, `check_p110`, `check_kindle`)
   - Configure basic service parameters and **Save**

4. **Add Custom Fields**

   - In the service template editor, navigate to the **Fields** tab
   - Click **Add Field** to define custom parameters for the command
   - Add variables like `gmodem2_rx_warning`, `p110_email`, `kindle_offline_hours`, etc.
   - **Save** the field definitions

5. **Configure Service Parameters**

   - Return to the service template main view
   - Set values for the custom parameters you defined
   - Configure check intervals, retry logic, and notification settings
   - **Save** the template

6. **Deploy Configuration**

   - Review pending changes in the **Activity Log**
   - Click **Deploy** to push the configuration to your Icinga infrastructure

#### Example Director Service Template

```
object CheckCommand "check_compose" {
    import "plugin-check-command"
    command = [ "/opt/nagios-plugins-lukas/check_compose" ]
    arguments = {
        "-p" = "$compose_project$"
        "--show-services" = { set_if = "$compose_show_services$" }
        "--ignore-services" = "$compose_ignore_services$"
    }
}
```

### Standard Nagios Plugins

This repository contains only the custom plugins. The standard nagios-plugins
(uniform build for all Linux hosts, parser and generated Icinga2 CheckCommands)
live in [nagios-plugins-general](https://github.com/ckbaker10/nagios-plugins-general).

## Usage Examples

### Fiber Modem
```
./check_gmodem2 -H 192.168.100.1 --rx-power-warning -15 --rx-power-critical -20
```

### Smart Plug
```
./check_p110 -H 10.10.10.138 -u "user@example.com" -p "password" --expect-on
```

### Printer
```
./check_jetdirect -H printer.domain.com -t consumable -o black -w 85 -c 90
./check_jetdirect -H printer.domain.com -t page
```

### Infrastructure Validation
```
./check_goss -g /etc/goss/server.yaml --show-failures
```

### Docker Compose
```
./check_compose -p icinga-playground --show-services
./check_compose -f /opt/myapp/docker-compose.yml --unhealthy-warning
```

### Kindle Device
```
./check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --offline-hours 8.0
```

### SMART Drive Health
```
./check_smart -d /dev/sda -i ata
./check_smart -d /dev/sda -i ata -b 5 -w "Reallocated_Sector_Ct=10"
./check_smart -g '/dev/sd[a-z]' -i scsi -q
```

### Hardware Sensors
```
./check_lm_sensors --list
./check_lm_sensors --high temp1=50,60 --high temp2=50,60
./check_lm_sensors --low fan1=2000,1000 --high 'sda Temp'=50,60
```

## Docker Setup

The check_compose plugin requires Docker access. The installation script automatically adds the nagios user to the docker group if Docker is installed.

Note: Restart Nagios/Icinga service after installation for docker group changes to take effect.

## Dependencies

All dependencies are managed by UV in an isolated virtual environment:

- requests - HTTP client library
- pycryptodome - Cryptographic functions
- pysnmp - SNMP protocol implementation
- pydantic - Data validation
- pkcs7 - Cryptographic padding
- urllib3 - HTTP utilities

## Troubleshooting

### Permission Issues

```
sudo chown -R nagios:nagios /opt/nagios-plugins-lukas
sudo chmod +x /opt/nagios-plugins-lukas/check_*
```

### Virtual Environment Issues

```
cd /opt/nagios-plugins-lukas
sudo -u nagios uv venv .venv --clear
sudo -u nagios uv pip install -e .
```

### Docker Access Issues

```
sudo usermod -aG docker nagios
sudo systemctl restart nagios
```

### Test Plugin

```
sudo -u nagios /opt/nagios-plugins-lukas/check_p110 -H device.local -u user -p pass -v
```

## Manual Installation

If you prefer manual setup:

```bash
# Install dependencies
uv venv .venv
uv pip install -e .

# Set permissions
sudo chown -R nagios:nagios /opt/nagios-plugins-lukas
sudo chmod +x /opt/nagios-plugins-lukas/check_*

# Add nagios to docker group (for check_compose)
sudo usermod -aG docker nagios

# Configure sudo rules for check_smart and check_lm_sensors
sudo tee /etc/sudoers.d/nagios-plugins > /dev/null << 'EOF'
# Nagios plugins - minimal permissions for hardware monitoring
# Allow nagios user to run smartctl, sensors, and hddtemp without password
Defaults:nagios !requiretty
nagios ALL=(root) NOPASSWD: /usr/sbin/smartctl
nagios ALL=(root) NOPASSWD: /usr/bin/sensors
nagios ALL=(root) NOPASSWD: /usr/sbin/hddtemp
EOF

# Set correct permissions on sudoers file
sudo chmod 0440 /etc/sudoers.d/nagios-plugins

# Validate sudoers syntax
sudo visudo -c -f /etc/sudoers.d/nagios-plugins
```

**Note:** The paths for `smartctl`, `sensors`, and `hddtemp` may vary by distribution:
- Debian/Ubuntu: `/usr/sbin/smartctl`, `/usr/bin/sensors`, `/usr/sbin/hddtemp`
- RHEL/CentOS: Check with `which smartctl sensors hddtemp`

Adjust the sudoers file paths accordingly for your system.

## Contributing

1. Follow Nagios plugin conventions
2. Include performance data in standard format
3. Provide comprehensive error handling
4. Add tests and documentation
5. Update pyproject.toml for dependencies

## License

GPLv3 - See LICENSE file for details.
