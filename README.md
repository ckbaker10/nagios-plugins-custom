# Nagios Plugins Collection

My personal nagios plugins, suited for my environment

![Nagios Plugins](pics/rVuPqNb.png)

## Overview

Mail route and public JSON checks: [`check_mail_report`](README-MAIL-REPORT.md)
supports direct probes, existing reports and the regular local Postfix/DKIM route.

These plugins are tested only by me using them in my own environment.
They are shipped as one self-contained x86_64 bundle per release
(current: [v1.4.1](https://github.com/ckbaker10/nagios-plugins-custom/releases/tag/v1.4.1))
and installed with the Ansible role in `ansible/`.

## Available Plugins

- check_gmodem2 - Telekom Glasfasermodem 2 fiber optic modem monitoring
- check_p110 - TP-Link Tapo P110 smart plug monitoring (passthrough, KLAP and TPAP)
- check_jetdirect - Network printer monitoring via SNMP
- check_goss - Infrastructure validation using Goss framework
- check_compose - Docker Compose service health monitoring
- check_eap772 - TP-Link Omada EAP772 access point monitoring via SNMPv3
- check_kindle - Kindle device monitoring via custom management platform API
- check_smart - SMART drive health monitoring for ATA/SCSI/NVMe devices
- check_lm_sensors - Hardware sensor monitoring (temperature, fans, voltages) and HDD temperatures
- check_space_usage - Disk space usage analysis by directory (respects mount points, excludes network mounts)
- check_lpr - LPD/LPR printer daemon protocol testing (RFC 1179)
- notify_sms - Icinga2 notification command: SMS through an OpenWrt LTE router
- check_lte_router - OpenWrt LTE router: SIM, registration, signal (RSRP/RSRQ/SINR), LTE data and internet (status script `sms-gateway/icinga-lte-status`, installed with `sms-gateway/install-status.sh`)

For detailed plugin documentation see [README-CHECKS.md](README-CHECKS.md)

## Tapo protocols (KLAP and TPAP)

`check_p110` speaks KLAP and the older passthrough protocol. Plugs on newer
firmware (seen with 1.4.0 Build 251020) switched to **TPAP** and reject the
KLAP handshake with HTTP 403. With `--protocol auto` (default) the plugin
then uses TPAP via python-kasa (pinned to the tested commit of
[python-kasa PR #1592](https://github.com/python-kasa/python-kasa/pull/1592),
not yet released) and remembers the protocol per plug in the temp dir.
Force with `--protocol legacy` or `--protocol tpap`.

A plug accepts only one session at a time; checks of the same plug are
serialized with a lock and transient errors are retried (`--retries`,
`--retry-delay`, `--lock-timeout`).

### Third-party Vendor Compatibility

Local access to Tapo plugs requires **Third-party Vendor Compatibility** to
be enabled in the Tapo app (device settings). Without it the plug rejects
local logins. A plug that still fails with HTTP 403 while this is enabled
most likely switched to TPAP, which `--protocol auto` handles.

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
- adds the check user to the `docker` group if it exists (check_compose)
- optional: SMS relay user and router key (`nagios_plugins_custom_sms_gateway`,
  `nagios_plugins_custom_sms_relay_keys`) and the LTE status key
  (`nagios_plugins_custom_lte_router`), see below
- skips hosts that are not x86_64

The check user defaults to `nagios` on Debian/Ubuntu and `icinga` on
RHEL/SUSE (`nagios_plugins_custom_user`).

Verify:

```
sudo -u nagios /opt/nagios-plugins-lukas/check_lm_sensors --version
cat /opt/nagios-plugins-lukas/BUILDINFO
```

### Build and release

```bash
build/build.sh      # dist/nagios-plugins-custom-<version>-x86_64.tar.gz, ~30 s
tests/e2e/run.sh    # acceptance test, see below
build/release.sh    # GitHub release v<version>, needs gh auth login
```

`tests/e2e/run.sh` builds the bundle and installs it in throwaway Podman
containers of every supported distribution (Rocky 8/9/10, Debian 12/13,
Ubuntu 22.04/24.04/26.04, openSUSE Leap 15.6/16.0). Each run checks the
SHA-256 file, `BUILDINFO`, `--help` of every plugin, the bundled Python
dependencies, and runs `check_goss` (passing and failing test) and
`check_space_usage`. `E2E_TARBALL=dist/…tar.gz` tests an existing bundle;
image names as arguments limit the run. Run it before every release.

The version comes from `pyproject.toml`. Dependencies: edit
`requirements.in`, then lock with the command at its top.

### Without Ansible

```bash
v=1.4.1
curl -fLO https://github.com/ckbaker10/nagios-plugins-custom/releases/download/v$v/nagios-plugins-custom-$v-x86_64.tar.gz
curl -fLO https://github.com/ckbaker10/nagios-plugins-custom/releases/download/v$v/nagios-plugins-custom-$v-x86_64.tar.gz.sha256
sha256sum -c nagios-plugins-custom-$v-x86_64.tar.gz.sha256
sudo tar -C / -xzf nagios-plugins-custom-$v-x86_64.tar.gz
sudo ln -sfn /opt/nagios-plugins-custom-$v /opt/nagios-plugins-lukas
```

Then create the sudoers rules (`ansible/roles/deploy-nagios-plugins-custom/templates/sudoers.j2`)
and, for `check_lpr`, a copy of the system python with
`setcap cap_net_bind_service=+ep` as `/opt/nagios-plugins-custom-$v/python3-lpr`.

### Legacy installation

`install.sh` and the shell wrappers `check_*` in the repository root belong
to the old setup (git checkout plus per-host uv venv in `/opt/nagios-plugins-lukas`).
They are replaced by the bundle, which generates its own wrappers; the
legacy setup pulls unpinned dependencies on every host.

## SMS notifications (notify_sms, sms-gateway)

Icinga2 notifications as SMS through an OpenWrt LTE router with a modem that
accepts AT commands (tested: ZTE MF289F).

```
Icinga master --ssh--> agent: icinga-sms (forced command: notify_sms --relay)
                         --ssh--> router: icinga-sms (forced command, allow list) --AT+CMGS--> SMS
```

- `sms-gateway/icinga-sms` on the router sends one SMS via the modem's AT
  port, only to numbers in `/etc/icinga-sms.allow`, GSM-safe text, max. 160
  characters. Install with
  `sms-gateway/install.sh root@ROUTER AGENT_PUBKEY +49...`.
- `notify_sms` sends via the router; `--relay` reads the fields as
  `KEY=VALUE` lines from stdin. The role creates the relay user
  (`nagios_plugins_custom_sms_gateway`, `nagios_plugins_custom_sms_relay_keys`).
- Icinga 2.15 does not execute notification commands on a
  `command_endpoint`, so when only the agent can reach the router, the
  master pipes the fields to the agent via SSH (example: NotificationCommand
  `sms-relay` in the home-network documentation). If the master reaches the
  router itself, use the NotificationCommand `sms-notification` from
  `commands-custom.conf`.

## LTE router monitoring (check_lte_router)

`sms-gateway/icinga-lte-status` runs on the router as forced command of a
dedicated key and prints SIM, registration, operator, band,
RSRP/RSRQ/RSSI/SINR, LTE data state and a ping through LTE. Setup:

1. Agent: set `nagios_plugins_custom_lte_router` and run the role; it prints
   the public key of the check user.
2. Router: `sms-gateway/install-status.sh root@ROUTER PUBKEY_FILE`.
3. Icinga: CheckCommand `check_lte_router` (`commands-custom.conf`), host
   address = router; thresholds `lte_router_rsrp_warning`/`_critical`
   (default −115/−125 dBm), `lte_router_sinr_warning`/`_critical` (0/−5 dB).

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
sudo cp icinga-custom-commands/commands-custom.conf /etc/icinga2/conf.d/
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
   sudo cp icinga-custom-commands/commands-custom.conf \
       /etc/icinga2/zones.d/global-templates/
   ```

   With [docker-compose-icinga](https://github.com/ckbaker10/docker-compose-icinga)
   the global zone is the `global-zone/` directory of the compose project.

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
./check_compose -p icinga-monitoring-main --show-services
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

### Smart Plug (TPAP firmware, explicit)
```
./check_p110 -H 10.10.10.139 -u "user@example.com" -p "password" --expect-on --protocol tpap
```

### LTE Router
```
./check_lte_router --router root@10.10.10.210 --rsrp-warning -115 --rsrp-critical -125
```

### SMS (dry run)
```
./notify_sms --to +4917... --type PROBLEM --host "Pump" --service tapo-status-on --state CRITICAL --dry-run
```

### Hardware Sensors
```
./check_lm_sensors --list
./check_lm_sensors --high temp1=50,60 --high temp2=50,60
./check_lm_sensors --low fan1=2000,1000 --high 'sda Temp'=50,60
```

## Docker Setup

`check_compose` needs access to the Docker daemon. The Ansible role adds the
check user to the `docker` group when that group exists; restart the Icinga
agent afterwards so the new group membership takes effect.

## Dependencies

Bundled in `lib/` of the release tarball, locked with SHA-256 hashes in
`requirements.txt` (edit `requirements.in`, then re-lock with the command at
its top):

- requests, urllib3 - HTTP (check_gmodem2, check_kindle, check_p110)
- pycryptodome, pkcs7 - KLAP/passthrough encryption (check_p110)
- python-kasa - TPAP transport (check_p110); pinned to commit `e7084472` of
  [PR #1592](https://github.com/python-kasa/python-kasa/pull/1592) until a
  release contains TPAP, plus its dependencies (aiohttp, cryptography,
  ecdsa, passlib, mashumaro, …)
- pyyaml - check_compose
- psutil - check_space_usage

System programs installed by the role: smartmontools, lm-sensors, net-snmp
tools (snmpget/snmpwalk for check_eap772 and check_jetdirect), setcap. The
bundle contains Python 3.12 and goss (check_goss).

## Troubleshooting

### Bundle

```
cat /opt/nagios-plugins-lukas/BUILDINFO          # version, Python, goss, build OS
readlink /opt/nagios-plugins-lukas               # active version
sudo -u nagios /opt/nagios-plugins-lukas/check_p110 -H device.local -u user -p pass -v
```

### Tapo plugs

- Sporadic HTTP 403 / "Invalid signature": two sessions on one plug at the
  same time. Fixed by the per-plug lock; make sure all checks of a plug run
  on the same agent.
- Permanent HTTP 403 at handshake1: plug uses TPAP. Check with
  `uvx --from python-kasa kasa --target BROADCAST discover raw`
  (`encrypt_type`). The detected protocol is cached in
  `/tmp/check_p110-<host>.protocol`; delete it to re-detect.

### Docker access

```
id -nG nagios        # must contain docker
```

### Sensors

`check_lm_sensors` calls `sensors -Aj` without sudo; on timeout (`-t`,
default 15 s) it returns UNKNOWN instead of a traceback.

## Contributing

1. Follow Nagios plugin conventions
2. Include performance data in standard format
3. Provide comprehensive error handling
4. Add tests and documentation
5. Add imported packages to requirements.in and re-lock requirements.txt
6. Bump the version in pyproject.toml, `build/build.sh`, `build/release.sh`

## License

GPL-3.0-or-later (see `pyproject.toml`).
