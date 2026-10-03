# Nagios Plugin Checks Documentation

This document describes the available Nagios monitoring plugins in this repository.

## Overview

This collection provides monitoring plugins for various network devices and system validation tools. All plugins follow standard Nagios conventions with proper exit codes, performance data, and comprehensive error handling.

## Available Plugins

### check_gmodem2

**Purpose**: Monitor Telekom Glasfasermodem 2 fiber optic modems via HTTP API

**Usage**:
```bash
check_gmodem2 -H <hostname> [options]
```

**Key Features**:
- Real-time optical power monitoring (RX/TX power levels)
- Link status and stability monitoring
- PLOAM (Physical Layer Operations Administration and Maintenance) status checking
- Hardware state validation
- Firmware version reporting
- Network statistics (packets, bytes, drops, errors)

**Thresholds**:
- `--rx-power-warning`: RX optical power warning threshold in dBm
- `--rx-power-critical`: RX optical power critical threshold in dBm

**Performance Data**: Includes optical power levels, packet statistics, byte counters, and error rates

**Common Use Cases**:
- Fiber connection quality monitoring
- ISP service level validation
- Network infrastructure health checks

---

### check_p110

**Purpose**: Monitor TP-Link P110 smart plugs with energy monitoring capabilities

**Usage**:
```bash
check_p110 -H <hostname> -u <email> -p <password> [options]
```

**Key Features**:
- Protocols: passthrough, KLAP and TPAP (newer firmware); `--protocol auto`
  falls back to TPAP when the plug rejects the KLAP handshake with HTTP 403
  and remembers the protocol per plug (`/tmp/check_p110-<host>.protocol`)
- One session per plug: checks of the same plug are serialized with a lock,
  connection/session errors are retried with a fresh handshake
- Device power state monitoring
- Energy consumption tracking (current power, daily/monthly usage)
- Signal strength monitoring (WiFi RSSI and signal level)
- Safety status monitoring (power protection, overcurrent, charging status)
- State expectation validation

**Authentication**: Requires TP-Link cloud account credentials

**Connection options**:
- `--protocol auto|legacy|tpap` (default auto)
- `--retries` (default 2), `--retry-delay` (default 3 s), `--lock-timeout` (default 30 s)
- `-t/--timeout`: connection timeout in seconds (default 10)

**Thresholds**:
- `--power-warning/--power-critical`: Power consumption thresholds in Watts
- `--signal-warning/--signal-critical`: WiFi signal level thresholds
- `--expect-on/--expect-off`: Expected device state validation
- `--expect-power-protection`: Expected power protection status
- `--expect-overcurrent`: Expected overcurrent protection status
- `--expect-charging`: Expected charging status

**Performance Data**: Power consumption, energy usage, signal strength, device status

**Common Use Cases**:
- Smart home device monitoring
- Power consumption analysis
- Remote device availability checking
- Energy usage reporting

---

### check_kindle

**Purpose**: Monitor Kindle e-reader devices through a custom Kindle management platform API, tracking battery levels, connectivity status, and deep sleep behavior

**Usage**:
```bash
check_kindle -u <api_url> -s <serial> [options]
```

**Key Features**:
- Device connectivity and online status monitoring
- Battery level tracking with configurable thresholds
- Deep sleep mode support with configurable offline grace period
- Last seen timestamp tracking
- Device model and hostname identification
- IP address and serial number reporting
- SSL/TLS support with optional certificate verification

**Required Arguments**:
- `-u, --url`: Base URL of the Kindle API (e.g., http://10.10.10.8:22116/api)
- `-s, --serial`: Kindle device serial number (e.g., B077-XXXX-XXXX)

**Optional Arguments**:
- `--battery-warning`: Battery level warning threshold in percent (default: 25)
- `--battery-critical`: Battery level critical threshold in percent (default: 15)
- `--offline-hours`: Hours device can be offline before triggering CRITICAL (default: 4.0, for deep sleep mode)
- `--timeout`: HTTP request timeout in seconds (default: 10)
- `--insecure`: Disable SSL certificate verification
- `--test-connection`: Test API connectivity before checking device
- `--show-details`: Show additional device details (IP, serial) in output
- `-v, --verbose`: Verbose output for debugging

**Deep Sleep Mode Handling**:
Kindle devices enter deep sleep mode to conserve battery, making them appear offline for extended periods. The `--offline-hours` parameter prevents false alarms:
- If offline < threshold hours: Status OK with "Device in sleep mode" message
- If offline > threshold hours: Status CRITICAL with "Device OFFLINE" alert
- Default: 4.0 hours (adjust based on your devices' sleep patterns)

**Performance Data**:
- `battery`: Battery level percentage with warning/critical thresholds
- `offline`: Binary indicator (1=offline, 0=online)
- `offline_hours`: Actual hours since last seen

**Common Use Cases**:
- E-reader fleet management
- Battery level monitoring and maintenance scheduling
- Device availability tracking with sleep mode awareness
- Remote device health validation

**Example Commands**:

Basic monitoring with default thresholds:
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX
```

Custom battery thresholds:
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --battery-warning 20 --battery-critical 10
```

Allow 8 hours of deep sleep before alerting:
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --offline-hours 8.0
```

Allow overnight sleep (12 hours):
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --offline-hours 12.0
```

With SSL and detailed output:
```bash
check_kindle -u https://kindle-api.example.com/api -s B077-XXXX-XXXX --show-details
```

Self-signed certificate support:
```bash
check_kindle -u https://10.10.10.8:22116/api -s B077-XXXX-XXXX --insecure
```

Test API connectivity:
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --test-connection --timeout 30
```

Verbose debugging:
```bash
check_kindle -u http://10.10.10.8:22116/api -s B077-XXXX-XXXX --show-details -v
```

**Icinga2 Configuration Example**:
```
object CheckCommand "check_kindle" {
  command = [ "/opt/nagios-plugins-lukas/check_kindle" ]
  
  arguments = {
    "-u" = {
      value = "$kindle_api_url$"
      required = true
    }
    "-s" = {
      value = "$kindle_serial$"
      required = true
    }
    "--battery-warning" = "$kindle_battery_warning$"
    "--battery-critical" = "$kindle_battery_critical$"
    "--offline-hours" = "$kindle_offline_hours$"
    "--timeout" = "$kindle_timeout$"
    "--insecure" = {
      set_if = "$kindle_insecure$"
    }
    "--test-connection" = {
      set_if = "$kindle_test_connection$"
    }
    "--show-details" = {
      set_if = "$kindle_show_details$"
    }
    "-v" = {
      set_if = "$kindle_verbose$"
    }
  }
}

object Service "Kindle Battery" {
  host_name = "kindle-living-room"
  check_command = "check_kindle"
  
  vars.kindle_api_url = "http://10.10.10.8:22116/api"
  vars.kindle_serial = "B077-1234-5678"
  vars.kindle_battery_warning = 25
  vars.kindle_battery_critical = 15
  vars.kindle_offline_hours = 8.0
}

# Example: Monitoring device with overnight sleep allowance
object Service "Kindle Bedroom" {
  host_name = "kindle-bedroom"
  check_command = "check_kindle"
  
  vars.kindle_api_url = "http://10.10.10.8:22116/api"
  vars.kindle_serial = "B077-8765-4321"
  vars.kindle_offline_hours = 12.0  # Allow overnight sleep
  vars.kindle_show_details = true
}

# Example: HTTPS with self-signed certificate
object Service "Kindle Office" {
  host_name = "kindle-office"
  check_command = "check_kindle"
  
  vars.kindle_api_url = "https://kindle-api.local/api"
  vars.kindle_serial = "B077-9999-1111"
  vars.kindle_insecure = true
  vars.kindle_timeout = 15
}
```

**Nagios Configuration Example**:
```
define command {
    command_name    check_kindle
    command_line    /opt/nagios-plugins-lukas/check_kindle -u $ARG1$ -s $ARG2$ --battery-warning $ARG3$ --battery-critical $ARG4$ --offline-hours $ARG5$
}

define command {
    command_name    check_kindle_basic
    command_line    /opt/nagios-plugins-lukas/check_kindle -u $ARG1$ -s $ARG2$
}

define service {
    use                     generic-service
    host_name               kindle-living-room
    service_description     Kindle Battery
    check_command           check_kindle!http://10.10.10.8:22116/api!B077-1234-5678!25!15!8.0
}

define service {
    use                     generic-service
    host_name               kindle-bedroom
    service_description     Kindle Status
    check_command           check_kindle!http://10.10.10.8:22116/api!B077-8765-4321!20!10!12.0
}
```

**API Response Format**:
The plugin expects the API endpoint `/monitoring/battery/{serial}` to return JSON in this format:
```json
{
  "device": {
    "serial": "B077-XXXX-XXXX",
    "hostname": "kindle-kt2",
    "model": "Kindle Touch 2",
    "battery": "85",
    "last_seen": "2025-10-30T10:15:30Z",
    "is_offline": false,
    "ip": "192.168.1.100"
  }
}
```

**Status Logic**:
1. **Device Offline**: 
   - If `is_offline=true` AND `offline_hours > --offline-hours`: CRITICAL
   - If `is_offline=true` AND `offline_hours ≤ --offline-hours`: OK (sleep mode)
2. **Device Online**:
   - Battery ≤ critical threshold: CRITICAL
   - Battery ≤ warning threshold: WARNING
   - Otherwise: OK

**Troubleshooting**:

Common issues and solutions:

1. **API connection failed**:
   - Verify the API URL is correct and accessible
   - Check network connectivity
   - Ensure API service is running
   - Try with `--test-connection` flag

2. **Device not found (404)**:
   - Verify the serial number is correct
   - Check that the device is registered in the API
   - Confirm the API endpoint format matches expectations

3. **SSL certificate verification failed**:
   - Use `--insecure` flag for self-signed certificates
   - Or install the proper CA certificate
   - Or use HTTP instead of HTTPS if acceptable

4. **Timeout errors**:
   - Increase timeout with `--timeout` option
   - Check API server performance
   - Verify network latency

5. **False offline alerts**:
   - Increase `--offline-hours` threshold to match device sleep patterns
   - Monitor actual sleep duration in performance data
   - Consider device-specific sleep schedules

6. **Invalid API response format**:
   - Enable verbose mode with `-v` to see actual API response
   - Verify API version compatibility
   - Check API documentation for expected format

---

### check_compose

**Purpose**: Monitor Docker Compose services and container health status

**Usage**:
```bash
check_compose [options]
check_compose -p <project_name> [options]
check_compose -f <compose_file> [options]
check_compose -d <directory> [options]
```

**Key Features**:
- Multi-project Docker Compose monitoring
- Service state detection (running, stopped, unhealthy, restarting)
- Container health status validation
- Automatic compose command detection (docker compose vs docker-compose)
- Configurable severity levels for unhealthy containers
- Service-level failure reporting
- Performance data for service counts

**Options**:
- `-p/--project`: Specify Docker Compose project name
- `-f/--file`: Path to specific docker-compose.yml file
- `-d/--directory`: Directory containing docker-compose.yml
- `--unhealthy-warning`: Treat unhealthy containers as WARNING instead of CRITICAL
- `--show-services`: Include individual service details in output
- `--ignore-services`: Comma-separated list of service names to ignore (e.g., 'init-icinga2,backup')

**Status Detection**:
- **Running**: Service is up and operational
- **Unhealthy**: Service is running but health check fails
- **Stopped**: Service has exited or is not running
- **Restarting**: Service is in restart loop
- **Other**: Unknown or error states

**Performance Data**: Includes total services, running count, unhealthy count, stopped count, and other state count

**Security**: Requires Docker access permissions.

**Common Use Cases**:
- Container orchestration monitoring
- Application stack health validation
- Microservices deployment verification
- Development environment status checks

---

### check_jetdirect

**Purpose**: Monitor network printers via SNMP protocol

**Usage**:
```bash
check_jetdirect -H <hostname> [options]
```

**Key Features**:
- Multiple check types: consumables, page counts, printer information
- Automatic printer compatibility detection
- Multiple OID support for different printer models
- Consumable level monitoring (toner, ink cartridges, drums)
- Page counter tracking
- Printer identification and status

**Arguments**:
- `-H, --hostname`: Printer hostname or IP address (required)
- `-C, --community`: SNMP community string (default: public)
- `-t, --type`: Check type - `consumable`, `page`, or `info` (default: page)
- `-o, --consumable`: Consumable type when using `-t consumable` - `black`, `cyan`, `magenta`, `yellow`, or `drum` (default: black)
- `-w, --warning`: Warning threshold for consumable usage percentage (default: 0)
- `-c, --critical`: Critical threshold for consumable usage percentage (default: 0)
- `-v, --verbose`: Enable verbose debugging output

**Check Types**:
- `page`: Monitor total page count (default)
- `consumable`: Monitor toner/ink levels with thresholds
- `info`: Retrieve printer model and serial number

**Consumable Types**: 
Use with `-o` option when check type is `consumable`:
- `black`: Black toner/ink cartridge
- `cyan`: Cyan toner/ink cartridge
- `magenta`: Magenta toner/ink cartridge
- `yellow`: Yellow toner/ink cartridge
- `drum`: Drum unit

**Performance Data**: Page counts, consumable usage percentages

**Dependencies**: Requires net-snmp-utils (snmpget/snmpwalk commands)

**Common Use Cases**:
- Print fleet management
- Consumable inventory tracking
- Printer availability monitoring
- Usage statistics collection

---

### check_goss

**Purpose**: Execute Goss validation tests and report infrastructure compliance

**Usage**:
```bash
check_goss [-g <goss_file>] [options]
```

**Key Features**:
- Infrastructure as code validation
- Multiple output format support (rspecish, TAP, JSON, JUnit)
- Variable file support for templating
- Package manager specific testing
- Failure detail reporting
- Any test failure treated as CRITICAL (infrastructure binary principle)

**Configuration Options**:
- `-g/--goss-file`: Path to Goss YAML configuration file
- `--vars`: Variables file for Goss templating
- `--package`: Package manager for package tests (apk, deb, pacman, rpm)
- `-f/--format`: Output format selection

**Performance Data**: Test counts, pass/fail statistics, failure percentage

**Dependencies**: Requires goss binary in PATH

**Common Use Cases**:
- Server configuration validation
- Compliance checking
- Infrastructure drift detection
- Deployment verification
- Security baseline validation

## General Plugin Features

### Standard Nagios Compliance
- Exit codes: 0 (OK), 1 (WARNING), 2 (CRITICAL), 3 (UNKNOWN)
- Performance data output for graphing and trending
- Comprehensive help documentation
- Timeout handling and error management

### Common Options
- `-H/--hostname`: Target device hostname or IP address
- `-t/--timeout`: Connection timeout in seconds
- `-v/--verbose`: Debug output for troubleshooting
- `-V/--version`: Plugin version information
- `--help`: Detailed usage information and examples

### Error Handling
- Network connectivity validation
- Authentication failure detection
- Protocol compatibility checking
- Graceful degradation with informative error messages
- Timeout protection for all network operations

## Installation Requirements

### Python Dependencies
Bundled in the release tarball (standalone Python 3.12 plus `lib/`), locked
with hashes in `requirements.txt`; see the Dependencies section of
[README.md](README.md). No pip/venv on the hosts.

### System Dependencies
- net-snmp tools (check_jetdirect, check_eap772)
- smartmontools (check_smart), lm-sensors (check_lm_sensors)
- goss: included in the bundle (`bin/goss`)
- Installed by the Ansible role `deploy-nagios-plugins-custom`

### File Permissions
Ensure plugins are executable:
```bash
chmod +x check_*
```

## Integration Examples

### Nagios Configuration
```
define command {
    command_name    check_gmodem2
    command_line    $USER1$/check_gmodem2 -H $HOSTADDRESS$ --rx-power-warning -15 --rx-power-critical -20
}

define command {
    command_name    check_p110
    command_line    $USER1$/check_p110 -H $HOSTADDRESS$ -u $ARG1$ -p $ARG2$ --power-warning 1000
}

define command {
    command_name    check_docker_compose
    command_line    $USER1$/check_compose -p $ARG1$ $ARG2$
}

define command {
    command_name    check_docker_compose_file
    command_line    $USER1$/check_compose -f $ARG1$ $ARG2$
}
```

### Command Line Testing
```bash
# Test fiber modem with optical power thresholds
./check_gmodem2 -H 192.168.100.1 --rx-power-warning -15 --rx-power-critical -20

# Monitor smart plug with power and state validation
./check_p110 -H 192.168.1.100 -u user@example.com -p password --expect-on --power-warning 50

# Check printer toner levels
./check_jetdirect -H printer.domain.com -t consumable -o black -w 85 -c 90

# Validate server configuration
./check_goss -g /etc/goss/server.yaml --show-failures

# Monitor Docker Compose services
./check_compose -p icinga-playground --show-services

# Monitor compose stack with file path
./check_compose -f /opt/myapp/docker-compose.yml --unhealthy-warning

# Ignore init containers and backups
./check_compose -p icinga-playground --ignore-services init-icinga2,backup
```

---

### check_smart

**Purpose**: Monitor disk drive health using SMART (Self-Monitoring, Analysis and Reporting Technology) for ATA, SCSI, and NVMe devices

**Usage**:
```bash
check_smart -d <device> -i <interface> [options]
check_smart -g <glob_pattern> -i <interface> [options]
```

**Key Features**:
- Support for ATA, SCSI, and NVMe drives
- Hardware RAID support (MegaRAID, 3ware, Areca, HP Smart Array, CCISS, AAC RAID, USB JMicron)
- Global device checking with pattern matching
- Comprehensive SMART attribute monitoring
- Self-test log validation
- Temperature monitoring with thresholds
- Load cycle count tracking
- SSD lifetime monitoring
- Configurable attribute exclusions
- Raw value threshold checking
- Performance data for trending

**Required Arguments**:
- `-d, --device`: Block device to monitor (e.g., /dev/sda) OR
- `-g, --global`: Glob pattern for multiple devices (e.g., '/dev/sd[a-z]')
- `-i, --interface`: Device interface type (required)

**Interface Types**:
- `auto` - Automatic detection
- `ata` - ATA/SATA drives
- `scsi` - SCSI drives
- `nvme` - NVMe drives
- `sat` - SATA drives on FreeBSD
- `megaraid,N` - LSI MegaRAID controller (disk N)
- `3ware,N` - 3ware RAID controller (port N)
- `areca,N` - Areca RAID controller
- `hpt,L/M/N` - HighPoint RocketRAID
- `cciss,N` - HP Smart Array (CCISS)
- `aacraid,H,L,ID` - Adaptec/PMC RAID
- `usbjmicron,N` - USB JMicron bridge

**Optional Arguments**:
- `-b, --bad`: Threshold for Current_Pending_Sector (ATA) or grown defect list (SCSI)
- `-w, --warn`: Comma-separated warning thresholds (e.g., "Reallocated_Sector_Ct=10,Current_Pending_Sector=5")
- `-r, --raw`: Comma-separated list of attributes to check raw values
- `-e, --exclude`: Comma-separated list of attributes to exclude from checks
- `-E, --exclude-all`: Comma-separated list of attributes to exclude from checks AND perfdata
- `-s, --selftest`: Enable self-test log error checking
- `-l, --ssd-lifetime`: Check Percent_Lifetime_Remain attribute (SSDs)
- `-O, --oldage`: Ignore old age attributes (unreliable on some drives)
- `-q, --quiet`: Only show faulted drives when using global check
- `--skip-self-assessment`: Skip SMART overall health status check
- `--skip-temp-check`: Skip temperature threshold validation
- `--skip-load-cycles`: Skip load cycle count alerts (600K safe threshold)
- `--skip-error-log`: Skip ATA error log checking
- `--hide-sn`: Hide drive serial number in output
- `--debug`: Show detailed debugging information

**Default Monitored Attributes (ATA)**:
- Current_Pending_Sector - Sectors waiting to be remapped
- Reallocated_Sector_Ct - Count of reallocated sectors
- Program_Fail_Cnt_Total - Flash program failures (SSDs)
- Uncorrectable_Error_Cnt - Uncorrectable errors
- Offline_Uncorrectable - Sectors that could not be corrected offline
- Runtime_Bad_Block - Runtime bad block detection
- Reported_Uncorrect - Reported uncorrectable errors
- Reallocated_Event_Count - Count of remap operations
- Erase_Fail_Count_Total - Flash erase failures (SSDs)
- Command_Timeout - Command timeout events

**Default Monitored Attributes (NVMe)**:
- Media_and_Data_Integrity_Errors - Media and data integrity error count

**Performance Data**:
All SMART attributes are exported as performance data for historical graphing and trending, including:
- Raw attribute values
- Temperature (current and maximum)
- Start/stop cycle counts
- Error counters
- Defect list counts (SCSI)

**Common Use Cases**:
- Proactive disk failure prediction
- Drive health monitoring and maintenance scheduling
- RAID array member validation
- SSD wear leveling tracking
- Data center disk fleet management
- Storage infrastructure health monitoring

**Example Commands**:

Basic ATA drive check:
```bash
check_smart -d /dev/sda -i ata
```

SCSI drive with bad sector threshold:
```bash
check_smart -d /dev/sdb -i scsi -b 5
```

NVMe drive check:
```bash
check_smart -d /dev/nvme0n1 -i nvme
```

Hardware RAID (MegaRAID disk 0):
```bash
check_smart -d /dev/sda -i megaraid,0
```

Multiple MegaRAID disks:
```bash
check_smart -d /dev/sda -i 'megaraid,[0-5]'
```

Global check for all SATA drives:
```bash
check_smart -g '/dev/sd[a-z]' -i ata
```

Global check with quiet mode (only show failures):
```bash
check_smart -g '/dev/sd*' -i scsi -q
```

Custom warning thresholds:
```bash
check_smart -d /dev/sda -i ata -w "Reallocated_Sector_Ct=10,Current_Pending_Sector=5"
```

SSD lifetime monitoring:
```bash
check_smart -d /dev/sda -i ata -l
```

Skip temperature and load cycle checks:
```bash
check_smart -d /dev/sda -i ata --skip-temp-check --skip-load-cycles
```

Enable selftest log checking:
```bash
check_smart -d /dev/sda -i ata -s
```

Exclude specific attributes:
```bash
check_smart -d /dev/sda -i ata -e "Power_On_Hours,Temperature_Celsius"
```

Debug mode:
```bash
check_smart -d /dev/sda -i ata --debug
```

**Icinga2 Configuration Example**:
```
object CheckCommand "check_smart" {
  command = [ "/opt/nagios-plugins-lukas/check_smart" ]
  
  arguments = {
    "-d" = "$smart_device$"
    "-g" = "$smart_global_pattern$"
    "-i" = {
      value = "$smart_interface$"
      required = true
    }
    "-b" = "$smart_bad_threshold$"
    "-e" = "$smart_exclude$"
    "-E" = "$smart_exclude_all$"
    "-r" = "$smart_raw_list$"
    "-w" = "$smart_warn_list$"
    "-s" = {
      set_if = "$smart_selftest$"
    }
    "-l" = {
      set_if = "$smart_ssd_lifetime$"
    }
    "-O" = {
      set_if = "$smart_oldage$"
    }
    "-q" = {
      set_if = "$smart_quiet$"
    }
    "--skip-self-assessment" = {
      set_if = "$smart_skip_self_assessment$"
    }
    "--skip-temp-check" = {
      set_if = "$smart_skip_temp_check$"
    }
    "--skip-load-cycles" = {
      set_if = "$smart_skip_load_cycles$"
    }
    "--skip-error-log" = {
      set_if = "$smart_skip_error_log$"
    }
    "--hide-sn" = {
      set_if = "$smart_hide_sn$"
    }
  }
}

# Example: Monitor single ATA drive
object Service "SMART /dev/sda" {
  host_name = "server01"
  check_command = "check_smart"
  
  vars.smart_device = "/dev/sda"
  vars.smart_interface = "ata"
  vars.smart_warn_list = "Reallocated_Sector_Ct=10,Current_Pending_Sector=5"
  vars.smart_selftest = true
}

# Example: Monitor SSD with lifetime tracking
object Service "SMART SSD /dev/sdb" {
  host_name = "server01"
  check_command = "check_smart"
  
  vars.smart_device = "/dev/sdb"
  vars.smart_interface = "ata"
  vars.smart_ssd_lifetime = true
  vars.smart_skip_load_cycles = true
}

# Example: Monitor MegaRAID array
object Service "SMART RAID Disks" {
  host_name = "raid-server"
  check_command = "check_smart"
  
  vars.smart_device = "/dev/sda"
  vars.smart_interface = "megaraid,[0-7]"
  vars.smart_bad_threshold = 5
}

# Example: Global check for all drives
object Service "SMART All Drives" {
  host_name = "storage-server"
  check_command = "check_smart"
  
  vars.smart_global_pattern = "/dev/sd*"
  vars.smart_interface = "scsi"
  vars.smart_quiet = true
}
```

**Nagios Configuration Example**:
```
define command {
    command_name    check_smart
    command_line    /opt/nagios-plugins-lukas/check_smart -d $ARG1$ -i $ARG2$
}

define command {
    command_name    check_smart_thresholds
    command_line    /opt/nagios-plugins-lukas/check_smart -d $ARG1$ -i $ARG2$ -w $ARG3$
}

define command {
    command_name    check_smart_global
    command_line    /opt/nagios-plugins-lukas/check_smart -g $ARG1$ -i $ARG2$ -q
}

define service {
    use                     generic-service
    host_name               server01
    service_description     SMART /dev/sda
    check_command           check_smart!/dev/sda!ata
}

define service {
    use                     generic-service
    host_name               server01
    service_description     SMART /dev/sdb
    check_command           check_smart_thresholds!/dev/sdb!ata!Reallocated_Sector_Ct=10,Current_Pending_Sector=5
}

define service {
    use                     generic-service
    host_name               storage-server
    service_description     SMART All Drives
    check_command           check_smart_global!/dev/sd*!scsi
}
```

**Hardware RAID Examples**:

LSI MegaRAID:
```bash
# Single disk
check_smart -d /dev/sda -i megaraid,0

# Multiple disks
check_smart -d /dev/sda -i 'megaraid,[0-7]'
```

3ware RAID:
```bash
# Single port
check_smart -d /dev/sda -i 3ware,0

# Multiple ports
check_smart -d /dev/sda -i '3ware,[0-3]'
```

HP Smart Array (CCISS):
```bash
check_smart -d /dev/cciss/c0d0 -i cciss,0
check_smart -d /dev/cciss/c0d0 -i 'cciss,[0-5]'
```

AAC RAID:
```bash
check_smart -d /dev/sda -i aacraid,0,0,0
check_smart -d /dev/sda -i 'aacraid,[0-3]'
```

**Troubleshooting**:

Common issues and solutions:

1. **smartctl not found**:
   - Install smartmontools package: `apt-get install smartmontools` or `yum install smartmontools`
   - Verify smartctl is in PATH: `which smartctl`
   - Check system paths: /usr/bin, /usr/sbin, /usr/local/bin

2. **Permission denied**:
   - Plugin requires root/sudo access to read SMART data
   - Ensure nagios user can run sudo smartctl
   - Add to sudoers: `nagios ALL=(ALL) NOPASSWD: /usr/sbin/smartctl`

3. **Device could not be opened**:
   - Verify device exists: `ls -l /dev/sda`
   - Check device permissions
   - Ensure device supports SMART: `smartctl -i /dev/sda`
   - Try different interface type (ata vs scsi vs auto)

4. **No health status line found**:
   - Device may not support SMART health status
   - Use `--skip-self-assessment` to bypass health check
   - Verify with manual test: `smartctl -H /dev/sda`

5. **False positives on old drives**:
   - Use `-O` flag to ignore old age attributes
   - Exclude specific attributes: `-e "attribute_name"`
   - Adjust warning thresholds: `-w "attribute=value"`

6. **High load cycle count warnings**:
   - Common on laptop drives (frequent parking)
   - Use `--skip-load-cycles` to disable alert
   - Modern drives support millions of cycles

7. **Temperature warnings**:
   - Use `--skip-temp-check` to disable
   - Check drive specifications for max temperature
   - Verify cooling and ventilation

8. **Hardware RAID not detected**:
   - Verify RAID controller driver is loaded
   - Check interface syntax matches controller type
   - Consult smartmontools wiki for specific controller support
   - Try `smartctl --scan` to detect available devices

**Notes**:
- Originally developed by Kurt Yoder (Public Domain)
- Maintained by Claudio Kuenzler
- Converted to Python 3 by Claude Sonnet 4.5 (Oct 2025)
- Official documentation: https://www.claudiokuenzler.com/monitoring-plugins/check_smart.php
- Requires smartmontools (smartctl binary)
- Global checks do not output perfdata (by design)
- Supports sudo execution for privilege elevation

## Performance Data Format

All plugins output performance data in Nagios standard format:
```
'label'=value[UOM];[warn];[crit];[min];[max]
```

Where:
- UOM: Unit of measurement (W, dBm, %, c for counters)
- warn/crit: Warning and critical thresholds
- min/max: Minimum and maximum expected values

This enables integration with monitoring dashboards, trending systems, and alerting tools.

## Troubleshooting

### Common Issues
1. **Permission denied**: Verify plugin executable permissions
2. **Module not found**: Install required Python dependencies
3. **Connection timeout**: Check network connectivity and firewall rules
4. **Authentication failed**: Verify credentials and account access
5. **SNMP timeout**: Confirm SNMP community strings and device configuration

### Debug Mode
Use `-v/--verbose` flag for detailed troubleshooting information:
```bash
./check_p110 -H device.local -u user -p pass -v
```

This provides protocol discovery details, authentication steps, and API response data for problem diagnosis.

---

### check_eap772

**Purpose**: Monitor TP-Link Omada EAP772 access points via SNMPv3 protocol

**Usage**:
```bash
check_eap772 -H <hostname> -u <username> -p <password> [options]
```

**Key Features**:
- System information monitoring (uptime, description, location, contact)
- Network interface status tracking (up/down detection)
- Interface traffic monitoring (bytes in/out with rate calculation)
- Error rate monitoring (errors, discards per interface)
- Critical interface validation (eth0, br0 must be operational)
- Comprehensive performance data for trending

**Required Arguments**:
- `-H, --host`: Hostname or IP address of the EAP772 access point
- `-u, --username`: SNMPv3 username (e.g., "monitoring")
- `-p, --password`: SNMPv3 authentication password (MD5 protocol)

**Optional Arguments**:
- `--error-threshold`: Error count threshold for warning (default: 100)
- `--ignore-errors`: Ignore interface error counts in status determination
- `--ignore-down`: Ignore down interfaces in status determination (useful for statistics tracking)
- `-i, --interfaces`: Comma-separated list of interfaces to monitor (e.g., 'eth0,br0'). If not specified, monitors default set: eth0, br0, wifi0, wifi1, wifi2, ath0, ath10, ath20
- `--show-interfaces`: Show interface status in output
- `-v, --verbose`: Enable verbose output for debugging

**SNMPv3 Configuration**:
- Security Level: authNoPriv (authentication without encryption)
- Auth Protocol: MD5
- No encryption protocol required
- Standard SNMP OIDs used (IF-MIB)

**Performance Data**:
For each network interface:
- `{interface}_bytes_in`: Inbound bytes counter
- `{interface}_bytes_out`: Outbound bytes counter
- `{interface}_errors_in`: Inbound error counter
- `{interface}_errors_out`: Outbound error counter
- `{interface}_discards_in`: Inbound discard counter
- `{interface}_discards_out`: Outbound discard counter
- `{interface}_status`: Interface operational status (1=up, 2=down)

**Common Use Cases**:
- Wireless access point health monitoring
- Network interface status validation
- Traffic and error rate trending
- Critical interface availability tracking (uplink and management)

**Example Commands**:

Basic monitoring:
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword
```

With custom error threshold:
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword --error-threshold 1000
```

Ignore error counts:
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword --ignore-errors
```

Monitor only specific interfaces:
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword -i eth0,br0
```

Statistics tracking mode (ignore all errors and down interfaces):
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword --ignore-errors --ignore-down
```

Verbose debugging:
```bash
check_eap772 -H 10.10.10.231 -u monitoring -p MySecurePassword -v
```

**Icinga2 Configuration Example**:
```
object CheckCommand "eap772" {
  command = [ "/opt/nagios-plugins-lukas/check_eap772" ]
  
  arguments = {
    "-H" = "$eap772_host$"
    "-u" = "$eap772_username$"
    "-p" = "$eap772_password$"
    "--error-threshold" = "$eap772_error_threshold$"
    "--ignore-errors" = {
      set_if = "$eap772_ignore_errors$"
    }
    "--ignore-down" = {
      set_if = "$eap772_ignore_down$"
    }
    "-i" = "$eap772_interfaces$"
    "--show-interfaces" = {
      set_if = "$eap772_show_interfaces$"
    }
  }
}

object Service "EAP772 Health" {
  host_name = "ap-office-1"
  check_command = "eap772"
  
  vars.eap772_host = "10.10.10.231"
  vars.eap772_username = "monitoring"
  vars.eap772_password = "MySecurePassword"
  vars.eap772_error_threshold = 1000
}

# Example: Monitor only critical interfaces and ignore errors
object Service "EAP772 Critical Interfaces" {
  host_name = "ap-office-2"
  check_command = "eap772"
  
  vars.eap772_host = "10.10.10.232"
  vars.eap772_username = "monitoring"
  vars.eap772_password = "MySecurePassword"
  vars.eap772_interfaces = "eth0,br0"
  vars.eap772_ignore_errors = true
}

# Example: Statistics tracking (always OK, only collect performance data)
object Service "EAP772 Statistics" {
  host_name = "ap-office-3"
  check_command = "eap772"
  
  vars.eap772_host = "10.10.10.233"
  vars.eap772_username = "monitoring"
  vars.eap772_password = "MySecurePassword"
  vars.eap772_ignore_errors = true
  vars.eap772_ignore_down = true
}
```

**Nagios Configuration Example**:
```
define command {
    command_name    check_eap772
    command_line    /opt/nagios-plugins-lukas/check_eap772 -H $ARG1$ -u $ARG2$ -p $ARG3$ --error-threshold $ARG4$
}

define command {
    command_name    check_eap772_filtered
    command_line    /opt/nagios-plugins-lukas/check_eap772 -H $ARG1$ -u $ARG2$ -p $ARG3$ -i $ARG4$ --ignore-errors
}

define command {
    command_name    check_eap772_stats
    command_line    /opt/nagios-plugins-lukas/check_eap772 -H $ARG1$ -u $ARG2$ -p $ARG3$ --ignore-errors --ignore-down
}

define service {
    use                     generic-service
    host_name               ap-office-1
    service_description     EAP772 Health
    check_command           check_eap772!10.10.10.231!monitoring!MySecurePassword!1000
}

define service {
    use                     generic-service
    host_name               ap-office-2
    service_description     EAP772 Critical Interfaces
    check_command           check_eap772_filtered!10.10.10.232!monitoring!MySecurePassword!eth0,br0
}

define service {
    use                     generic-service
    host_name               ap-office-3
    service_description     EAP772 Statistics
    check_command           check_eap772_stats!10.10.10.233!monitoring!MySecurePassword
}
```

**Monitored SNMP OIDs**:
- `.1.3.6.1.2.1.1.1.0` - sysDescr (System description)
- `.1.3.6.1.2.1.1.3.0` - sysUpTime (System uptime)
- `.1.3.6.1.2.1.1.4.0` - sysContact (System contact)
- `.1.3.6.1.2.1.1.5.0` - sysName (System name)
- `.1.3.6.1.2.1.1.6.0` - sysLocation (System location)
- `.1.3.6.1.2.1.2.2.1.2` - ifDescr (Interface descriptions)
- `.1.3.6.1.2.1.2.2.1.8` - ifOperStatus (Interface operational status)
- `.1.3.6.1.2.1.2.2.1.10` - ifInOctets (Inbound byte counter)
- `.1.3.6.1.2.1.2.2.1.14` - ifInErrors (Inbound error counter)
- `.1.3.6.1.2.1.2.2.1.16` - ifOutOctets (Outbound byte counter)
- `.1.3.6.1.2.1.2.2.1.19` - ifInDiscards (Inbound discard counter)
- `.1.3.6.1.2.1.2.2.1.20` - ifOutErrors (Outbound error counter)
- `.1.3.6.1.2.1.2.2.1.13` - ifOutDiscards (Outbound discard counter)

**Troubleshooting**:

Common issues and solutions:

1. **SNMPv3 authentication failure**: 
   - Verify username and password are correct
   - Confirm auth protocol is MD5 (not SHA)
   - Security level must be authNoPriv (not authPriv)
   - Check that SNMPv3 user is configured on the device

2. **SNMP timeout**:
   - Verify network connectivity to the device
   - Check firewall rules allow UDP port 161
   - Confirm SNMP service is enabled on the EAP772
   - Try with verbose mode to see SNMP command details

3. **Critical interface down**:
   - eth0 or br0 interfaces are required to be operational
   - Check physical network connections
   - Verify device configuration
   - Review device logs for hardware issues

4. **High error rates**:
   - Investigate network quality issues
   - Check for cable problems or interference
   - Review switch port statistics for duplex mismatches
   - Adjust thresholds if normal for environment

5. **Missing performance data**:
   - Ensure SNMP permissions include IF-MIB read access
   - Verify OID support with snmpwalk testing

---

### check_lm_sensors

**Purpose**: Monitor hardware sensors (CPU/system temperatures, fan speeds, voltages) using lm_sensors and hard disk temperatures using hddtemp.

**Requirements**:
- lm_sensors package installed (`sensors` binary)
- Optional: hddtemp for drive temperature monitoring
- Sensors must be properly configured (run `sensors-detect` first)
- Root/sudo access may be required for hddtemp; `sensors` runs without sudo
- `sensors -Aj` is called once per check; `-t/--timeout` (default 15 s)
  returns UNKNOWN if it does not finish

**Version**: 3.2.0

**Plugin Type**: System Health Monitoring

**Parameters**:

| Parameter | Short | Type | Required | Default | Description |
|-----------|-------|------|----------|---------|-------------|
| --high | - | string | No | - | Check for high values: sensor=warn,crit (can be used multiple times) |
| --low | -l | string | No | - | Check for low values: sensor=warn,crit (can be used multiple times) |
| --range | -r | string | No | - | Check value range: sensor=warn,crit,reference (can be used multiple times) |
| --check | -c | string | No | - | Deprecated check syntax (use --high or --range instead) |
| --rename | - | string | No | - | Rename sensor: newname=oldname (can be used multiple times) |
| --sanitize | - | flag | No | false | Remove spaces from sensor names |
| --nosensors | - | flag | No | false | Disable lm_sensors checks |
| --nodrives | - | flag | No | false | Disable drive temperature checks |
| --drives | -d | flag | No | false | Enable drive temperature checks (redundant, enabled by default) |
| --hddtemp_bin | - | string | No | auto-detect | Path to hddtemp binary |
| --sensors_bin | - | string | No | auto-detect | Path to sensors binary |
| --list | - | flag | No | false | List all available sensors and exit |
| --verbose | -v | flag | No | 0 | Verbose output (can be specified multiple times) |
| --version | - | flag | No | - | Display version and exit |

**Sensor Name Handling**:

Sensors with spaces in their names can be specified in multiple ways:
- Quoting: `--high 'sda Temp'=50,60`
- Underscore substitution: `--high sda_Temp=50,60`
- Sanitize option: `--sanitize --high sdaTemp=50,60`

**Check Types**:

1. **High Checks** (`--high`): Trigger when sensor value exceeds thresholds
   - Format: `sensor=warning,critical`
   - Example: `--high temp1=50,60` (warn at 50°C, critical at 60°C)
   - Use for: CPU temperature, system temperature, voltages

2. **Low Checks** (`--low`): Trigger when sensor value drops below thresholds
   - Format: `sensor=warning,critical`
   - Example: `--low fan1=2000,1000` (warn below 2000 RPM, critical below 1000 RPM)
   - Use for: Fan speeds, minimum voltages

3. **Range Checks** (`--range`): Trigger when sensor deviates from reference value
   - Format: `sensor=warning_delta,critical_delta,reference`
   - Example: `--range v1=1,2,12` (warn if outside 11-13V, critical if outside 10-14V)
   - Use for: Voltages that should stay near specific value

**Exit Codes**:
- 0 (OK): All sensors within specified thresholds
- 1 (WARNING): One or more sensors exceeded warning threshold
- 2 (CRITICAL): One or more sensors exceeded critical threshold
- 3 (UNKNOWN): Sensor not found or binary not available

**Performance Data**: Yes - All monitored sensors with their current values and thresholds

**Common Sensor Names**:
- Temperature: `temp1`, `temp2`, `Core 0`, `Core 1`, etc.
- Fans: `fan1`, `fan2`, `CPU Fan`, `System Fan`, etc.
- Voltages: `in0`, `in1`, `Vcore`, `+3.3V`, `+5V`, `+12V`, etc.
- Drives: `sda Temp`, `sdb Temp`, `nvme0 Temp`, etc.

**Common Use Cases**:
- CPU and motherboard temperature monitoring
- Fan failure detection
- Power supply voltage monitoring
- Hard disk temperature tracking
- Server room environmental monitoring

**Example Commands**:

List all available sensors:
```bash
check_lm_sensors --list
```

Monitor CPU temperature:
```bash
check_lm_sensors --high temp1=50,60 --high temp2=50,60
```

Monitor fan speeds:
```bash
check_lm_sensors --low fan1=2000,1000 --low fan2=2000,1000
```

Monitor voltages in range:
```bash
check_lm_sensors --range in0=0.1,0.2,3.3 --range in1=0.5,1.0,12.0
```

Monitor drive temperatures:
```bash
check_lm_sensors --high 'sda Temp'=50,60 --high 'sdb Temp'=50,60
```

Only monitor drives (disable sensors):
```bash
check_lm_sensors --nosensors --high 'sda Temp'=50,60
```

Combined monitoring with renamed sensors:
```bash
check_lm_sensors --high temp1=50,60 --low fan1=2000,1000 --rename cputemp=temp1 --rename cpufan=fan1
```

Using sanitized names:
```bash
check_lm_sensors --sanitize --high sdaTemp=50,60 --high sdbTemp=50,60
```

**Icinga2 Configuration Example**:
```
object CheckCommand "lm_sensors" {
  command = [ "/opt/nagios-plugins-lukas/check_lm_sensors" ]
  
  arguments = {
    "--high" = {
      value = "$lm_sensors_high$"
      repeat_key = true
    }
    "--low" = {
      value = "$lm_sensors_low$"
      repeat_key = true
    }
    "--range" = {
      value = "$lm_sensors_range$"
      repeat_key = true
    }
    "--rename" = {
      value = "$lm_sensors_rename$"
      repeat_key = true
    }
    "--sanitize" = {
      set_if = "$lm_sensors_sanitize$"
    }
    "--nosensors" = {
      set_if = "$lm_sensors_nosensors$"
    }
    "--nodrives" = {
      set_if = "$lm_sensors_nodrives$"
    }
    "-v" = {
      set_if = "$lm_sensors_verbose$"
    }
  }
}

object Service "sensors-cpu-temp" {
  host_name = "server01"
  check_command = "lm_sensors"
  
  vars.lm_sensors_high = [
    "temp1=50,60",
    "temp2=50,60"
  ]
  vars.lm_sensors_rename = [
    "cpu0=temp1",
    "cpu1=temp2"
  ]
}

object Service "sensors-fans" {
  host_name = "server01"
  check_command = "lm_sensors"
  
  vars.lm_sensors_low = [
    "fan1=2000,1000",
    "fan2=2000,1000"
  ]
}

object Service "sensors-drives" {
  host_name = "server01"
  check_command = "lm_sensors"
  
  vars.lm_sensors_high = [
    "sda Temp=50,60",
    "sdb Temp=50,60"
  ]
  vars.lm_sensors_nosensors = true
}
```

**Nagios Configuration Example**:
```
define command {
    command_name    check_lm_sensors_cpu
    command_line    /opt/nagios-plugins-lukas/check_lm_sensors --high temp1=50,60 --high temp2=50,60
}

define command {
    command_name    check_lm_sensors_fans
    command_line    /opt/nagios-plugins-lukas/check_lm_sensors --low fan1=2000,1000 --low fan2=2000,1000
}

define command {
    command_name    check_lm_sensors_drives
    command_line    /opt/nagios-plugins-lukas/check_lm_sensors --nosensors --high 'sda Temp'=$ARG1$ --high 'sdb Temp'=$ARG2$
}

define service {
    use                     generic-service
    host_name               server01
    service_description     CPU Temperature
    check_command           check_lm_sensors_cpu
}

define service {
    use                     generic-service
    host_name               server01
    service_description     System Fans
    check_command           check_lm_sensors_fans
}
```

**Setup Requirements**:

1. **Install lm_sensors**:
```bash
# Debian/Ubuntu
apt-get install lm-sensors

# RHEL/CentOS
yum install lm_sensors
```

2. **Detect and configure sensors**:
```bash
sensors-detect
# Answer 'yes' to all safe questions
# Add detected modules to /etc/modules or run modprobe commands

# Test detection
sensors
```

3. **Install hddtemp (optional)**:
```bash
# Debian/Ubuntu
apt-get install hddtemp

# RHEL/CentOS
yum install hddtemp
```

4. **Grant permissions for drive monitoring**:
```bash
# Add nagios user to disk group for hddtemp access
usermod -a -G disk nagios

# Or configure sudo access
echo "nagios ALL=(ALL) NOPASSWD: /usr/sbin/hddtemp" >> /etc/sudoers.d/nagios
```

**Troubleshooting**:

Common issues and solutions:

1. **No sensors found**:
   - Run `sensors-detect` to detect available sensors
   - Load required kernel modules: `modprobe <module_name>`
   - Verify sensors command works: `sensors`
   - Check that sensor chips are supported by lm_sensors

2. **Sensor not found in check**:
   - List available sensors: `check_lm_sensors --list`
   - Check sensor name spelling and capitalization
   - Try underscore vs. space in sensor name
   - Use `--sanitize` option to remove spaces

3. **hddtemp not working**:
   - Verify hddtemp is installed: `which hddtemp`
   - Test manually: `hddtemp /dev/sda`
   - Check disk permissions: `ls -l /dev/sda`
   - Add nagios user to disk group or configure sudo
   - Some drives don't support temperature reporting

4. **Permission denied errors**:
   - For drives: Add nagios user to disk group
   - For sensors: Usually accessible to all users
   - Check file permissions: `/sys/class/hwmon/*`
   - Use sudo wrapper if necessary

5. **Incorrect sensor values**:
   - Verify with manual sensors command: `sensors`
   - Check sensor configuration: `/etc/sensors3.conf`
   - Some sensors may need calibration
   - Consult motherboard documentation for correct sensor mappings

6. **JSON parsing errors** (sensors version issue):
   - Requires lm_sensors version 3.5.0 or higher for JSON support
   - Check version: `sensors --version`
   - Upgrade lm_sensors if needed
   - On older systems, consider using the Perl version

**Performance Data Format**:
```
sensor1=value;warn;crit;; sensor2=value;warn;crit;;
```

Example:
```
temp1=45;50;60;; fan1=2500;2000;1000;; in0=3.32;3.2;3.1;;
```

**Attribution**: 
- Original Perl version: Copyright (c) 2007, ETH Zurich
- Converted to Python: 2025
- License: GNU General Public License (GPL) version 3

---
   - Check that interface counters are being updated
   
## check_space_usage

### Purpose
Analyzes disk space usage by directory to identify which directories are consuming the most space. Respects mount points to ensure mounted filesystems are not counted towards their parent directories. Automatically excludes network mounts (CIFS, NFS).

### Features
- **Mount Point Aware**: Uses `du --one-file-system` to respect filesystem boundaries
- **Network Mount Exclusion**: Automatically detects and excludes CIFS/NFS/SMB mounts
- **Configurable Depth**: Scan subdirectories to specified depth level
- **Top N Reporting**: Report only the top directories by size
- **Threshold Support**: Optional warning/critical thresholds for filesystem usage
- **Performance Data**: Detailed perfdata including top directories
- **Compact/Detailed Output**: Choose between summary or detailed listing

### Usage
```bash
./check_space_usage -p <path> [options]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| -p, --path | No | / | Path to analyze |
| -d, --depth | No | 2 | Maximum directory depth to analyze |
| -t, --top | No | 10 | Number of top directories to report |
| -w, --warning | No | None | Warning threshold for filesystem usage (%) |
| -c, --critical | No | None | Critical threshold for filesystem usage (%) |
| -e, --exclude | No | None | Exclude paths (can be repeated) |
| --show-details | No | False | Show detailed list in output |
| -v, --verbose | No | False | Verbose debugging output |

### Examples

**Basic Usage**:
```bash
./check_space_usage -p /
```

**With Depth and Top N**:
```bash
./check_space_usage -p / --depth 3 --top 15
```

**With Thresholds**:
```bash
./check_space_usage -p /var -w 80 -c 90 --top 10
```

**With Exclusions**:
```bash
./check_space_usage -p / --exclude /tmp --exclude /var/tmp --depth 2
```

**Detailed Output**:
```bash
./check_space_usage -p / --show-details --top 5
```

**Verbose Debug Mode**:
```bash
./check_space_usage -p /var/lib --depth 2 -v
```

### Icinga2 Configuration

```
object CheckCommand "check_space_usage" {
    import "plugin-check-command"
    command = [ "/opt/nagios-plugins-lukas/check_space_usage" ]
    arguments = {
        "-p" = "$space_usage_path$"
        "-d" = "$space_usage_depth$"
        "-t" = "$space_usage_top$"
        "-w" = "$space_usage_warning$"
        "-c" = "$space_usage_critical$"
        "-e" = {
            value = "$space_usage_exclude$"
            repeat_key = true
        }
        "--show-details" = {
            set_if = "$space_usage_show_details$"
        }
    }
    vars.space_usage_path = "/"
    vars.space_usage_depth = 2
    vars.space_usage_top = 10
}
```

### Example Output

**Compact Format**:
```
OK - /: 53.9GB/58.0GB (93.0%) used | Top 3: /var: 12.7GB, /opt: 11.9GB, /usr: 8.5GB | used=57821143040B;;;0;62235250688 percent=93.0%;;;0;100
```

**Detailed Format**:
```
OK - /: 53.9GB/58.0GB (93.0%) used | Top 10 directories:
  1. /var: 12.7GB
  2. /opt: 11.9GB [MOUNT]
  3. /usr: 8.5GB
  4. /home: 5.2GB
  5. /root: 2.1GB
  ...
```

### Mount Point Handling

The plugin automatically detects mount points using `psutil.disk_partitions()`. For each mount point:
- Local filesystems (ext4, xfs, etc.): Shows used space from the mounted filesystem
- Network mounts (CIFS, NFS): **Completely excluded from analysis**

Example system with multiple mounts:
```
/                       ext4    (analyzed)
├── /var/lib/docker     ext4    (treated as separate mount)
├── /var/lib/opensearch ext4    (treated as separate mount)
└── /mnt/docushare      cifs    (excluded - network mount)
```

### Network Mount Detection

Automatically excludes these filesystem types:
- `cifs` - Common Internet File System (SMB/CIFS shares)
- `nfs` / `nfs4` - Network File System
- `smbfs` - SMB filesystem
- `davfs` - WebDAV filesystem  
- `fuse.sshfs` - SSHFS mounts

### Performance Data

```
used=<bytes>B;;;0;<total>
percent=<percent>%;warn;crit;0;100
dir1_<path>=<bytes>B;;;;
dir2_<path>=<bytes>B;;;;
...
```

### Troubleshooting

**Problem**: Analysis takes too long
- **Solution**: Reduce `--depth` parameter or exclude large directories

**Problem**: Permission denied errors
- **Solution**: Run as root or with appropriate permissions to read all directories

**Problem**: Network mount included in analysis
- **Solution**: Network mounts should be auto-detected. Use `--verbose` to see detection logic. If needed, use `--exclude /mnt/share`

**Problem**: Mount points not respected
- **Solution**: Verify `du` command works correctly with `--one-file-system` flag

**Problem**: Inaccurate sizes
- **Solution**: Check if directory is under a network mount. These are excluded by default.

### Dependencies
- Python 3.8+
- psutil (for mount point detection)

---

## check_lpr

### Purpose
Tests LPD (Line Printer Daemon) protocol connectivity and queue status. Implements RFC 1179 "Line Printer Daemon Protocol" by sending a short-form queue status request.

### Features
- **RFC 1179 Compliant**: Uses proper source port range (721-731)
- **Queue Status Query**: Sends 0x03 (short queue status) command
- **Timeout Support**: Configurable connection and response timeouts
- **Privilege Detection**: Clear error messages for permission issues
- **Response Time Tracking**: Performance data for monitoring trends

### Usage
```bash
./check_lpr -H <host> [options]
```

**Note**: RFC 1179 requires a source port 721-731. The bundle's `check_lpr`
wrapper uses `python3-lpr` (a copy of the system python with
`cap_net_bind_service`, created by the Ansible role) when present, so no
sudo is needed. Without it, run the plugin as root.

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| -H, --host | Yes | None | Hostname or IP of LPD server |
| -p, --port | No | 515 | LPD server port |
| -s, --source | No | 730 | Source port to bind (721-731) |
| -q, --queue | No | pr2 | Queue name to check |
| -t, --timeout | No | 10 | Connection timeout in seconds |
| -v, --verbose | No | False | Verbose debugging output |

### Examples

**Basic Usage**:
```bash
sudo ./check_lpr -H printer.domain.com
```

**Custom Queue and Port**:
```bash
sudo ./check_lpr -H 192.168.1.100 -q lp -s 725
```

**With Timeout**:
```bash
sudo ./check_lpr -H printserver -p 515 -q main_queue -t 15
```

**Verbose Debug**:
```bash
sudo ./check_lpr -H printer.local -q pr2 -v
```

### Icinga2 Configuration

```
object CheckCommand "check_lpr" {
    import "plugin-check-command"
    command = [ "/opt/nagios-plugins-lukas/check_lpr" ]
    arguments = {
        "-H" = {
            value = "$lpr_host$"
            required = true
        }
        "-p" = "$lpr_port$"
        "-s" = "$lpr_source_port$"
        "-q" = "$lpr_queue$"
        "-t" = "$lpr_timeout$"
    }
    vars.lpr_host = "$address$"
    vars.lpr_port = 515
    vars.lpr_source_port = 730
    vars.lpr_queue = "pr2"
}
```

**Permissions**: with the Ansible role, `python3-lpr` provides the
privileged port and no sudo is needed. The role also keeps a sudoers rule
for `/opt/nagios-plugins-lukas/check_lpr` as fallback; then use
`command = [ "sudo", "/opt/nagios-plugins-lukas/check_lpr" ]`.

### Example Output

**Success**:
```
OK - LPD: queue is ready and printing (0.034s response) | response_time=0.034s;;;0
```

**Connection Refused**:
```
CRITICAL - Connection refused by printer.domain.com:515 (0.002s response) | response_time=0.002s;;;0
```

**Permission Error**:
```
UNKNOWN - Permission denied binding to port 730. Run as root or use sudo. (0.000s response) | response_time=0.000s;;;0
```

### RFC 1179 Requirements

The LPD protocol (RFC 1179) requires that clients connect from a privileged source port in the range 721-731. This is a security measure to prevent unauthorized access to printer queues.

**Port Range**: 721-731  
**Default Used**: 730  
**Privilege Required**: root (or CAP_NET_BIND_SERVICE on Linux)

### Protocol Details

The plugin sends a short-form queue status request:
```
Format: <0x03><queue_name><newline>
Example: 0x03pr2\n
```

The LPD server responds with queue status information. Any response is considered successful (OK), as it indicates the daemon is running and responding.

### Performance Data

```
response_time=<seconds>s;;;0
```

### Troubleshooting

**Problem**: Permission denied binding to port
- **Solution**: Run with sudo: `sudo ./check_lpr -H host`
- **Or**: Configure sudoers as shown above

**Problem**: Connection refused
- **Solution**: Verify LPD service is running on target host
- **Check**: `telnet printer.domain.com 515`

**Problem**: Timeout
- **Solution**: Check network connectivity and firewall rules
- **Solution**: Increase timeout with `-t 30`

**Problem**: Source port already in use
- **Solution**: Try a different port in range 721-731: `-s 725`
- **Or**: Wait a few seconds for previous connection to close

**Problem**: Invalid queue name
- **Solution**: Verify queue name with printer administrator
- **Common names**: lp, pr2, main, default

### Security Considerations

1. **Privileged Ports**: Source ports 721-731 require root privileges
2. **Sudo Access**: Configure minimal sudo permissions for nagios user
3. **Network Security**: LPD protocol has no encryption - use on trusted networks only
4. **Firewall Rules**: Ensure port 515 is accessible from monitoring server

### Dependencies
- Python 3.8+
- Standard library only (no external dependencies)
- Root privileges (for source port binding)

### Historical Context

LPD protocol dates back to BSD Unix (1980s) and is still widely used for network printing. Modern alternatives include IPP (Internet Printing Protocol), but many enterprise environments still rely on LPD for legacy compatibility.

**Attribution**: 
- Original C version: Copyright (c) 2002 Scott Lurndal
- Converted to Python: 2025
- License: GNU General Public License (GPL) version 3

---

## check_lte_router

**Purpose**: Monitor an OpenWrt LTE router with a modem that accepts AT
commands (tested: ZTE MF289F): SIM, network registration, signal, LTE data
connection and internet reachability through LTE.

**How it works**: Reads `KEY=VALUE` status lines via SSH from
`sms-gateway/icinga-lte-status` on the router. The key used may only run that
script (forced command). The script shares the modem lock with `icinga-sms`.

**Usage**:
```bash
check_lte_router --router root@10.10.10.210 [options]
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| --router | root@10.10.10.210 | SSH target of the router |
| --identity | /var/lib/nagios/.ssh/icinga-lte | SSH key (forced command icinga-lte-status) |
| --known-hosts | /var/lib/nagios/.ssh/known_hosts_icinga_lte | Router host key |
| --rsrp-warning / --rsrp-critical | -115 / -125 | RSRP thresholds in dBm (lower is worse) |
| --sinr-warning / --sinr-critical | 0 / -5 | SINR thresholds in dB |
| --allow-roaming | off | Do not warn when roaming |
| -t, --timeout | 15 | SSH connect timeout |

**States**:
- CRITICAL: SIM not READY, not registered, LTE data interface down, no ping
  through LTE, RSRP/SINR below critical
- WARNING: RSRP/SINR below warning, roaming
- UNKNOWN: router not reachable via SSH

**Performance Data**: rsrp, rsrq, sinr, rssi, data_uptime

**Icinga2**: CheckCommand `check_lte_router` in `commands-custom.conf`
(variables `lte_router_*`, address from `$address$`).

## notify_sms

**Purpose**: Icinga2 notification command that sends an SMS through the LTE
router (`sms-gateway/icinga-sms`, `AT+CMGS`). One SMS (max. 160 GSM
characters) per notification: type, state, host, service, time, first line of
the output.

**Usage**:
```bash
notify_sms --to +4917... --type PROBLEM --host "Host" --service svc --state CRITICAL --output "..."
notify_sms --relay < fields.txt     # KEY=VALUE lines: to, type, host, service, state, time, output
notify_sms ... --dry-run            # print the message only
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| --gateway | root@10.10.10.210 | SSH target of the router |
| --identity | /var/lib/nagios/.ssh/icinga-sms | Key with forced command icinga-sms |
| --known-hosts | /var/lib/nagios/.ssh/known_hosts_icinga_sms | Router host key |
| --retries | 2 | Retries (not for rejected numbers) |

The router only sends to numbers in `/etc/icinga-sms.allow`. Icinga2 does not
run notification commands on a `command_endpoint`; if only an agent reaches
the router, the master pipes the fields to `notify_sms --relay` on that agent
via SSH (see README.md, SMS notifications).
