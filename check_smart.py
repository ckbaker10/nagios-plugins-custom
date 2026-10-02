#!/usr/bin/env python3
# Check SMART status of ATA/SCSI/NVMe drives, returning any usable metrics as perfdata.
# For usage information, run ./check_smart.py -h
#
# This script was initially created under contract for the US Government and is therefore Public Domain
#
# Official documentation: https://www.claudiokuenzler.com/monitoring-plugins/check_smart.php
#
# Converted to Python by Claude Sonnet 4.5
#
# Changes and Modifications
# =========================
# Feb 3, 2009: Kurt Yoder - initial version of script (rev 1.0)
# Jul 8, 2013: Claudio Kuenzler - support hardware raids like megaraid (rev 2.0)
# Jul 9, 2013: Claudio Kuenzler - update help output (rev 2.1)
# Oct 11, 2013: Claudio Kuenzler - making the plugin work on FreeBSD (rev 3.0)
# Oct 11, 2013: Claudio Kuenzler - allowing -i sat (SATA on FreeBSD) (rev 3.1)
# Nov 4, 2013: Claudio Kuenzler - works now with CCISS on FreeBSD (rev 3.2)
# Nov 4, 2013: Claudio Kuenzler - elements in grown defect list causes warning (rev 3.3)
# Nov 6, 2013: Claudio Kuenzler - add threshold option "bad" (-b) (rev 4.0)
# Nov 7, 2013: Claudio Kuenzler - modified help (rev 4.0)
# Nov 7, 2013: Claudio Kuenzler - bugfix in threshold logic (rev 4.1)
# Mar 19, 2014: Claudio Kuenzler - bugfix in defect list perfdata (rev 4.2)
# Apr 22, 2014: Jerome Lauret - implemented -g to do a global lookup (rev 5.0)
# Apr 25, 2014: Claudio Kuenzler - cleanup, merge Jeromes code, perfdata output fix (rev 5.1)
# May 5, 2014: Caspar Smit - Fixed output bug in global check / issue #3 (rev 5.2)
# Feb 4, 2015: Caspar Smit and cguadall - Allow detection of more than 26 devices / issue #5 (rev 5.3)
# Feb 5, 2015: Bastian de Groot - Different ATA vs. SCSI lookup (rev 5.4)
# Feb 11, 2015: Josh Behrends - Allow script to run outside of nagios plugins dir / wiki url update (rev 5.5)
# Feb 11, 2015: Claudio Kuenzler - Allow script to run outside of nagios plugins dir for FreeBSD too (rev 5.5)
# Mar 12, 2015: Claudio Kuenzler - Change syntax of -g parameter (glob is now awaited from input) (rev 5.6)
# Feb 6, 2017: Benedikt Heine - Fix Use of uninitialized value $device (rev 5.7)
# Oct 10, 2017: Bobby Jones - Allow multiple devices for interface type megaraid, e.g. "megaraid,[1-5]" (rev 5.8)
# Apr 28, 2018: Pavel Pulec (Inuits) - allow type "auto" (rev 5.9)
# May 5, 2018: Claudio Kuenzler - Check selftest log for errors using new parameter -s (rev 5.10)
# Dec 27, 2018: Claudio Kuenzler - Add exclude list (-e) to ignore certain attributes (5.11)
# Jan 8, 2019: Claudio Kuenzler - Fix 'Use of uninitialized value' warnings (5.11.1)
# Jun 4, 2019: Claudio Kuenzler - Add raw check list (-r) and warning thresholds (-w) (6.0)
# Jun 11, 2019: Claudio Kuenzler - Allow using pseudo bus device /dev/bus/N (6.1)
# Aug 19, 2019: Claudio Kuenzler - Add device model and serial number in output (6.2)
# Oct 1, 2019: Michael Krahe - Allow exclusion from perfdata as well (-E) and by attribute number (6.3)
# Oct 29, 2019: Jesse Becker - Remove dependency on utils.pm, add quiet parameter (6.4)
# Nov 22, 2019: Claudio Kuenzler - Add Reported_Uncorrect and Reallocated_Event_Count to default raw list (6.5)
# Nov 29, 2019: Claudio Kuenzler - Add 3ware and cciss devices for global (-g) check, adjust output (6.6)
# Dec 4, 2019: Ander Punnar - Fix 'deprecation warning on regex with curly brackets' (6.6.1)
# Mar 25, 2020: Claudio Kuenzler - Add support for NVMe devices (6.7.0)
# Jun 2, 2020: Claudio Kuenzler - Bugfix to make --warn work (6.7.1)
# Oct 14, 2020: Claudio Kuenzler - Allow skip self-assessment check (--skip-self-assessment) (6.8.0)
# Oct 14, 2020: Claudio Kuenzler - Add Command_Timeout to default raw list (6.8.0)
# Mar 3, 2021: Evan Felix - Allow use of colons in pathnames so /dev/disk/by-path/ device names work (6.9.0)
# Mar 4, 2021: Claudio Kuenzler - Add SSD attribute Percent_Lifetime_Remain check (-l|--ssd-lifetime) (6.9.0)
# Apr 8, 2021: Claudio Kuenzler - Fix regex for pseudo-devices (6.9.1)
# Jul 6, 2021: Bernhard Bittner - Add aacraid devices (6.10.0)
# Oct 4, 2021: Claudio Kuenzler + Peter Newman - Handle dots in NVMe attributes, prioritize (order) alerts (6.11.0)
# Dec 10, 2021: Claudio Kuenzler - Sec fix in path for pseudo-devices, add Erase_Fail_Count_Total, fix NVMe perfdata (6.12.0)
# Dec 10, 2021: Claudio Kuenzler - Bugfix in interface handling (6.12.1)
# Dec 16, 2021: Lorenz Kaestle - Bugfix when interface parameter was missing in combination with -g (6.12.2)
# Apr 27, 2022: Claudio Kuenzler - Allow skip temperature check (--skip-temp-check) (6.13.0)
# Apr 27, 2022: Peter Newman - Better handling of missing or non-executable smartctl command (6.13.0)
# Apr 29, 2023: Nick Bertrand - Show drive(s) causing UNKNOWN status using -g/--global check (6.14.0)
# Apr 29, 2023: Claudio Kuenzler - Add possibility to hide serial number (--hide-sn) (6.14.0)
# Apr 29, 2023: Claudio Kuenzler - Add default check on Load Cycle Count (ignore using --skip-load-cycles) (6.14.0)
# Sep 20, 2023: Yannick Martin - Fix default Percent_Lifetime_Remain threshold handling when -w is given (6.14.1)
# Sep 20, 2023: Claudio Kuenzler - Fix debug output for raw check list, fix --hide-serial in debug output (6.14.1)
# Mar 15, 2024: Yannick Martin - Fix nvme check when auto interface is given and device is nvme (6.14.2)
# Sep 10, 2024: Claudio Kuenzler - Fix performance data format, missing perfdata in SCSI drives (6.14.3)
# Jan 31, 2025: Tomas Barton - Ignore old age attributes due to its unrealiability. Check ATA error logs (6.15.0)
# Jun 12, 2025: Alexander Kanevskiy - Add usbjmicron devices (6.16.0)
# Oct 30, 2025: Converted from Perl to Python 3 by Claude Sonnet 4.5

import argparse
import sys
import os
import stat
import re
import glob as glob_module
import subprocess
from typing import List, Tuple, Dict, Optional

VERSION = '6.16.0'

# Standard Nagios return codes
ERRORS = {
    'OK': 0,
    'WARNING': 1,
    'CRITICAL': 2,
    'UNKNOWN': 3,
    'DEPENDENT': 4
}

# System paths to search for smartctl
SYS_PATH = [
    '/usr/bin', '/bin', '/usr/sbin', '/sbin',
    '/usr/local/bin', '/usr/local/sbin'
]


class SmartCheck:
    def __init__(self, args):
        self.args = args
        self.exit_status = 'OK'
        self.exit_status_local = 'OK'
        self.status_string = ''
        self.perf_string = ''
        self.terminator = ' --- '
        self.vendor = ''
        self.model = ''
        self.product = ''
        self.serial = ''
        
        # Find smartctl command
        self.smart_command = self.find_smartctl()
        
        # Setup exclude lists
        self.exclude_checks = args.exclude.split(',') if args.exclude else []
        exclude_perfdata = args.exclude_all.split(',') if args.exclude_all else []
        self.exclude_checks.extend(exclude_perfdata)
        self.exclude_perfdata = exclude_perfdata
        
        # Setup raw check lists
        default_raw_ata = 'Current_Pending_Sector,Reallocated_Sector_Ct,Program_Fail_Cnt_Total,Uncorrectable_Error_Cnt,Offline_Uncorrectable,Runtime_Bad_Block,Reported_Uncorrect,Reallocated_Event_Count,Erase_Fail_Count_Total,Command_Timeout'
        self.raw_check_list = (args.raw if args.raw else default_raw_ata).split(',')
        if args.ssd_lifetime:
            self.raw_check_list.append('Percent_Lifetime_Remain')
        
        default_raw_nvme = 'Media_and_Data_Integrity_Errors'
        self.raw_check_list_nvme = (args.raw if args.raw else default_raw_nvme).split(',')
        
        # Setup warning thresholds
        self.warn_list = {}
        if args.warn:
            for warn_element in args.warn.split(','):
                if '=' in warn_element:
                    key, value = warn_element.split('=', 1)
                    self.warn_list[key] = int(value)
        
        if args.ssd_lifetime and 'Percent_Lifetime_Remain' not in self.warn_list:
            self.warn_list['Percent_Lifetime_Remain'] = 90
        
        # For backward compatibility, add -b parameter to warning thresholds
        if args.bad:
            self.warn_list['Current_Pending_Sector'] = args.bad
        
        # Drive status tracking
        self.drives_status_okay = []
        self.drives_status_not_okay = []
        self.drives_status_warning = []
        self.drives_status_critical = []
        self.drives_status_unknown = []
        self.drive_details = None
    
    def find_smartctl(self) -> str:
        """Find smartctl executable in system paths"""
        for path in SYS_PATH:
            smartctl_path = os.path.join(path, 'smartctl')
            if os.path.isfile(smartctl_path) and os.access(smartctl_path, os.X_OK):
                return f"sudo {smartctl_path}"
        
        print("UNKNOWN - Could not find executable smartctl in " + ", ".join(SYS_PATH))
        sys.exit(ERRORS['UNKNOWN'])
    
    def debug(self, message: str):
        """Print debug message if debug mode is enabled"""
        if self.args.debug:
            sys.stderr.write(f"(debug) {message}\n")
    
    def escalate_status(self, requested_status: str):
        """Escalate exit status if more severe than previous"""
        if requested_status == 'WARNING':
            if self.exit_status == 'CRITICAL' or self.exit_status_local == 'CRITICAL':
                return
        if requested_status == 'UNKNOWN':
            if self.exit_status in ['WARNING', 'CRITICAL'] or self.exit_status_local in ['WARNING', 'CRITICAL']:
                return
        
        self.exit_status = requested_status
        self.exit_status_local = requested_status
    
    def get_devices(self) -> List[str]:
        """Get list of devices to check"""
        devices = []
        
        if self.args.device:
            devices.append(self.args.device)
        elif self.args.global_pattern:
            devices = glob_module.glob(self.args.global_pattern)
        
        # Filter valid block/character devices
        valid_devices = []
        for dev in devices:
            self.debug(f"Found {dev}")
            # Check if device exists and is a block or character device
            try:
                if os.path.exists(dev):
                    mode = os.stat(dev).st_mode
                    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
                        valid_devices.append(dev)
                    else:
                        self.debug(f"{dev} is not a valid block/character special device!")
                elif re.match(r'^/dev/bus/\d$', dev):
                    # Pseudo-device allowed
                    valid_devices.append(dev)
                else:
                    self.debug(f"{dev} does not exist!")
            except (OSError, PermissionError) as e:
                self.debug(f"Cannot access {dev}: {e}")
        
        if not valid_devices:
            pattern_str = self.args.device if self.args.device else self.args.global_pattern
            print(f"Could not find any valid block/character special device for {pattern_str}!\n")
            sys.exit(ERRORS['UNKNOWN'])
        
        return valid_devices
    
    def expand_interface(self, interface: str) -> List[str]:
        """Expand interface patterns like megaraid,[1-5]"""
        interfaces = []
        
        # Handle megaraid,[N-M] pattern
        match = re.match(r'(megaraid|3ware|cciss|aacraid|usbjmicron),\[(\d+)-(\d+)\]', interface)
        if match:
            prefix, start, end = match.groups()
            for i in range(int(start), int(end) + 1):
                interfaces.append(f"{prefix},{i}")
        else:
            interfaces.append(interface)
        
        return interfaces
    
    def run_command(self, command: str) -> Tuple[int, List[str]]:
        """Run shell command and return exit code and output lines"""
        self.debug(f"executing:\n{command}\n")
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                # A hanging drive must not block until Icinga kills the
                # plugin; TimeoutExpired (and PermissionError when killing
                # the root-owned sudo child) end up in the handler below
                timeout=60
            )
            output = result.stdout.splitlines()
            self.debug(f"output:\n{result.stdout}\n")
            return result.returncode, output
        except Exception as e:
            self.debug(f"Command failed: {e}")
            return 255, []
    
    def check_device(self, device: str, interface: str):
        """Check a single device"""
        error_messages = []
        warning_messages = []
        notice_messages = []
        self.exit_status_local = 'OK'
        
        # Determine label and tag for output
        if self.args.global_pattern:
            tag = device
            tag = tag.replace(self.args.global_pattern, '')
            if re.match(r'(?:megaraid|3ware|aacraid|cciss)', interface):
                label = f"[{interface}] - "
            else:
                label = f"[{device}] - "
        else:
            label = ""
            tag = device
        
        self.debug("###########################################################")
        self.debug(f"CHECK 1: getting overall SMART health status for {tag}")
        self.debug("###########################################################\n")
        
        # Build smartctl command
        hide_serial_flag = "-q noserial" if self.args.hide_sn else ""
        full_command = f"{self.smart_command} -d {interface} -Hi {device} {hide_serial_flag}"
        
        return_code, output = self.run_command(full_command)
        
        # Parse output
        output_mode = ""
        found_status = False
        
        line_str_ata = 'SMART overall-health self-assessment test result: '
        ok_str_ata = 'PASSED'
        line_str_scsi = 'SMART Health Status: '
        ok_str_scsi = 'OK'
        
        line_model_ata = 'Device Model: '
        line_model_nvme = 'Model Number: '
        line_vendor_scsi = 'Vendor: '
        line_model_scsi = 'Product: '
        line_serial_ata = 'Serial Number: '
        line_serial_scsi = 'Serial number: '
        
        for line in output:
            # Check SCSI health status
            if line_str_scsi in line:
                found_status = True
                output_mode = "scsi"
                self.debug(f"parsing line:\n{line}")
                status = line.split(line_str_scsi)[1].strip()
                if status == ok_str_scsi:
                    self.debug(f"found string '{ok_str_scsi}'; status OK")
                else:
                    self.debug(f"no '{ok_str_scsi}' status; failing")
                    if not self.args.skip_self_assessment:
                        error_messages.append(f"Health status: {status}")
                        self.escalate_status('CRITICAL')
            
            # Check ATA health status
            elif line_str_ata in line:
                found_status = True
                if interface == 'nvme':
                    output_mode = "nvme"
                    self.debug("setting output mode to nvme")
                elif not output_mode:
                    output_mode = "ata"
                self.debug(f"parsing line:\n{line}")
                status = line.split(line_str_ata)[1].strip()
                if status == ok_str_ata:
                    self.debug(f"found string '{ok_str_ata}'; status OK")
                else:
                    self.debug(f"no '{ok_str_ata}' status; failing")
                    if not self.args.skip_self_assessment:
                        error_messages.append(f"Health status: {status}")
                        self.escalate_status('CRITICAL')
            
            # Parse model information
            if line_model_ata in line:
                self.debug(f"parsing line:\n{line}")
                self.model = re.sub(r'\s{2,}', ' ', line.split(line_model_ata)[1].strip())
                self.debug(f"found model: {self.model}")
            
            if line_model_nvme in line:
                output_mode = "nvme"
                self.debug(f"parsing line:\n{line}")
                self.model = re.sub(r'\s{2,}', ' ', line.split(line_model_nvme)[1].strip())
                self.debug(f"found model: {self.model}")
            
            if line_vendor_scsi in line:
                self.debug(f"parsing line:\n{line}")
                self.vendor = line.split(line_vendor_scsi)[1].strip()
                self.debug(f"found vendor: {self.vendor}")
            
            if line_model_scsi in line:
                self.debug(f"parsing line:\n{line}")
                self.product = line.split(line_model_scsi)[1].strip()
                self.model = f"{self.vendor} {self.product}"
                self.model = re.sub(r'\s{2,}', ' ', self.model)
                self.debug(f"found model: {self.model}")
            
            # Parse serial number
            if line_serial_ata in line:
                self.debug(f"parsing line:\n{line}")
                if self.args.hide_sn:
                    self.serial = "<HIDDEN>"
                    self.debug("Hiding serial number")
                else:
                    self.serial = line.split(line_serial_ata)[1].strip()
                self.debug(f"found serial number {self.serial}")
            
            if line_serial_scsi in line:
                self.debug(f"parsing line:\n{line}")
                self.serial = line.split(line_serial_scsi)[1].strip()
                self.debug(f"found serial number {self.serial}")
        
        if not found_status:
            error_messages.append('No health status line found')
            self.escalate_status('UNKNOWN')
        
        # CHECK 2: Silent SMART health check
        self.debug("###########################################################")
        self.debug("CHECK 2: getting silent SMART health check")
        self.debug("###########################################################\n")
        
        full_command = f"{self.smart_command} -d {interface} -q silent -A {device}"
        self.debug(f"executing:\n{full_command}")
        
        return_code = subprocess.call(full_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.debug(f"exit code:\n{return_code}\n")
        
        if return_code & 0x01:
            error_messages.append('Commandline parse failure')
            self.escalate_status('UNKNOWN')
        if return_code & 0x02:
            error_messages.append('Device could not be opened')
            self.escalate_status('UNKNOWN')
        if return_code & 0x04:
            warning_messages.append('Checksum failure')
            self.escalate_status('WARNING')
        if return_code & 0x08:
            error_messages.append('Disk is failing')
            self.escalate_status('CRITICAL')
        if return_code & 0x10:
            warning_messages.append('Disk is in prefail')
            self.escalate_status('WARNING')
        if return_code & 0x20:
            warning_messages.append('Disk may be close to failure')
            self.escalate_status('WARNING')
        if return_code & 0x40:
            warning_messages.append('Error log contains errors')
            self.escalate_status('WARNING')
        if return_code & 0x80:
            warning_messages.append('Self-test log contains errors')
            self.escalate_status('WARNING')
        if return_code and not self.exit_status_local:
            error_messages.append('Unknown return code')
            self.escalate_status('CRITICAL')
        
        # Optional selftest log check
        if self.args.selftest:
            self.debug("selftest log check activated")
            full_command = f"{self.smart_command} -d {interface} -q silent -l selftest {device}"
            return_code = subprocess.call(full_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.debug(f"exit code:\n{return_code}")
            
            if return_code > 0:
                warning_messages.append('Self-test log contains errors')
                self.debug("Self-test log contains errors")
                self.escalate_status('WARNING')
        
        # CHECK 3: Detailed statistics
        self.debug("###########################################################")
        self.debug("CHECK 3: getting detailed statistics from attributes")
        self.debug("###########################################################\n")
        
        full_command = f"{self.smart_command} -d {interface} -a {device}"
        return_code, output = self.run_command(full_command)
        
        perfdata = []
        self.debug(f"Raw Check List ATA: {','.join(self.raw_check_list)}")
        self.debug(f"Raw Check List NVMe: {','.join(self.raw_check_list_nvme)}")
        self.debug(f"Exclude List for Checks: {','.join(self.exclude_checks)}")
        self.debug(f"Exclude List for Perfdata: {','.join(self.exclude_perfdata)}")
        self.debug("Warning Thresholds:")
        for k, v in sorted(self.warn_list.items()):
            self.debug(f"{k}={v}")
        
        # Parse attributes based on output mode
        if output_mode == "ata":
            perfdata.extend(self.parse_ata_attributes(output, error_messages, warning_messages, notice_messages))
        elif output_mode == "nvme":
            perfdata.extend(self.parse_nvme_attributes(output, error_messages, warning_messages, notice_messages))
        else:  # SCSI
            perfdata.extend(self.parse_scsi_attributes(output, error_messages, warning_messages))
        
        self.debug(f"gathered perfdata:\n{' '.join(perfdata)}\n")
        self.perf_string = ' '.join(perfdata)
        
        # Build status string
        self.debug("###########################################################")
        self.debug(f"LOCAL STATUS: {self.exit_status_local}, FINAL STATUS: {self.exit_status}")
        self.debug("###########################################################\n")
        
        if self.exit_status_local != 'OK':
            if self.args.global_pattern:
                status_string = label + ', '.join(error_messages + warning_messages + notice_messages)
            else:
                self.drive_details = f"Drive {self.model} S/N {self.serial}: "
                status_string = ', '.join(error_messages + warning_messages + notice_messages)
            
            if self.exit_status_local == 'WARNING':
                self.drives_status_warning.append(status_string)
            elif self.exit_status_local == 'CRITICAL':
                self.drives_status_critical.append(status_string)
            elif self.exit_status_local == 'UNKNOWN':
                self.drives_status_unknown.append(status_string)
        else:
            if self.args.global_pattern:
                status_string = label + "Device is clean"
                if error_messages:
                    status_string += " " + label + ', '.join(error_messages)
                if warning_messages:
                    status_string += " " + label + ', '.join(warning_messages)
                if notice_messages:
                    status_string += " " + label + ', '.join(notice_messages)
            else:
                self.drive_details = f"Drive {self.model} S/N {self.serial}: no SMART errors detected. "
                status_string = ', '.join(error_messages + warning_messages + notice_messages)
            
            self.drives_status_okay.append(status_string)
    
    def parse_ata_attributes(self, output: List[str], error_messages: List[str], 
                           warning_messages: List[str], notice_messages: List[str]) -> List[str]:
        """Parse ATA SMART attributes"""
        perfdata = []
        
        for line in output:
            # Check for ATA errors
            if not self.args.skip_error_log:
                match = re.match(r'^ATA Error Count:\s(\d+)\s', line)
                if match:
                    attribute_name = 'ata_errors'
                    raw_value = int(match.group(1))
                    
                    if attribute_name in self.warn_list and raw_value >= self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value})")
                        self.escalate_status('WARNING')
                    elif attribute_name in self.warn_list and raw_value < self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value}) but less than {self.warn_list[attribute_name]}")
                        notice_messages.append(f"{attribute_name} is non-zero ({raw_value}) (but less than threshold {self.warn_list[attribute_name]})")
                    elif raw_value > 0:
                        self.debug(f"{attribute_name} is non-zero ({raw_value})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value})")
                        self.escalate_status('WARNING')
                    
                    perfdata.append(f"{attribute_name}={raw_value};;;;")
            
            # Parse SMART attribute line
            match = re.match(r'^\s*(\d+)\s(\S+)\s+(?:\S+\s+){6}(\S+)\s+(\d+)', line)
            if not match:
                continue
            
            attribute_number, attribute_name, when_failed, raw_value = match.groups()
            attribute_number = int(attribute_number)
            raw_value = int(raw_value)
            
            # Check if attribute failed
            if when_failed != '-':
                if (attribute_number in [int(x) if x.isdigit() else -1 for x in self.exclude_checks] or
                    attribute_name in self.exclude_checks or
                    when_failed in self.exclude_checks):
                    self.debug(f"SMART Attribute {attribute_name} failed at {when_failed} but was set to be ignored")
                else:
                    if self.args.oldage and attribute_number == 202:
                        continue
                    warning_messages.append(f"Attribute {attribute_name} failed at {when_failed}")
                    self.escalate_status('WARNING')
                    self.debug(f"parsed SMART attribute {attribute_name} with error condition:\n{when_failed}")
            
            # Skip questionable attributes
            if attribute_name in ['Unknown_Attribute', 'Power_On_Minutes']:
                continue
            
            # Add to perfdata if not excluded
            if not (attribute_number in [int(x) if x.isdigit() else -1 for x in self.exclude_perfdata] or
                   attribute_name in self.exclude_perfdata):
                if self.args.device:
                    perfdata.append(f"{attribute_name}={raw_value};;;;")
            
            # Skip if in exclude list
            if (attribute_number in [int(x) if x.isdigit() else -1 for x in self.exclude_checks] or
                attribute_name in self.exclude_checks):
                self.debug(f"SMART Attribute {attribute_name} was set to be ignored")
                continue
            
            # Check load cycles
            if not self.args.skip_load_cycles and attribute_number == 193:
                if raw_value > 600000:
                    self.debug(f"{attribute_name} is above value considered safe (600K)")
                    error_messages.append(f"{attribute_name} is above 600K load cycles ({raw_value}) causing possible performance and durability impact")
                    self.escalate_status('CRITICAL')
                elif 550000 < raw_value < 600000:
                    self.debug(f"{attribute_name} is nearing 600K load cycles")
                    warning_messages.append(f"{attribute_name} is soon reaching 600K load cycles ({raw_value}) causing possible performance and durability impact soon")
            
            # Check raw value for significant attributes
            if attribute_name in self.raw_check_list:
                if raw_value > 0:
                    if attribute_name in self.warn_list and raw_value >= self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value})")
                        self.escalate_status('WARNING')
                    elif attribute_name in self.warn_list and raw_value < self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value}) but less than {self.warn_list[attribute_name]}")
                        notice_messages.append(f"{attribute_name} is non-zero ({raw_value}) (but less than threshold {self.warn_list[attribute_name]})")
                    else:
                        self.debug(f"{attribute_name} is non-zero ({raw_value})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value})")
                        self.escalate_status('WARNING')
                else:
                    self.debug(f"{attribute_name} is OK ({raw_value})")
            else:
                self.debug(f"{attribute_name} not in raw check list (raw value: {raw_value})")
        
        return perfdata
    
    def parse_nvme_attributes(self, output: List[str], error_messages: List[str],
                             warning_messages: List[str], notice_messages: List[str]) -> List[str]:
        """Parse NVMe SMART attributes"""
        perfdata = []
        
        for line in output:
            match = re.match(r'(\w.+):\s+(?:(\dx\d(?:\d?\w?)|\d(?:(?:,?\s?\d+,?\s?)?)+))', line)
            if not match:
                continue
            
            attribute_name, raw_value = match.groups()
            raw_value = re.sub(r'[\s,]', '', raw_value)
            attribute_name = attribute_name.replace(' ', '_').replace('.', '')
            
            # Skip irrelevant attributes for perfdata
            if attribute_name == 'Critical_Warning':
                self.exclude_perfdata.append(attribute_name)
            
            # Add to perfdata if not excluded
            if attribute_name not in self.exclude_perfdata:
                if self.args.device:
                    perfdata.append(f"{attribute_name}={raw_value};;;;")
            
            # Skip if in exclude list
            if attribute_name in self.exclude_checks:
                self.debug(f"SMART Attribute {attribute_name} was set to be ignored")
                continue
            
            # Handle Critical_Warning values
            if attribute_name == 'Critical_Warning':
                warning_map = {
                    '0x01': "Available spare below threshold",
                    '0x02': "Temperature is above or below thresholds",
                    '0x03': "Available spare below threshold and temperature is above or below thresholds",
                    '0x04': "NVM subsystem reliability degraded",
                    '0x05': "Available spare below threshold and NVM subsystem reliability degraded",
                    '0x06': "Temperature is above or below thresholds and NVM subsystem reliability degraded",
                    '0x07': "Available spare below threshold and Temperature is above or below thresholds and NVM subsystem reliability degraded",
                    '0x08': "Media in read only mode",
                    '0x09': "Media in read only mode and Available spare below threshold",
                    '0x0A': "Media in read only mode and Temperature is above or below thresholds",
                    '0x0B': "Media in read only mode and Temperature is above or below thresholds and Available spare below threshold",
                    '0x0C': "Media in read only mode and NVM subsystem reliability degraded",
                    '0x0D': "Media in read only mode and NVM subsystem reliability degraded and Available spare below threshold",
                    '0x0E': "Media in read only mode and NVM subsystem reliability degraded and Temperature is above or below thresholds",
                    '0x0F': "Media in read only mode and NVM subsystem reliability degraded and Temperature is above or below thresholds",
                    '0x10': "Volatile memory backup device failed"
                }
                
                if raw_value in warning_map:
                    if raw_value == '0x04' and self.args.oldage:
                        self.debug(f"{attribute_name} = '0x04' was set to be ignored due to oldage flag")
                    else:
                        warning_messages.append(warning_map[raw_value])
                        self.escalate_status('WARNING')
            
            # Check raw value for significant attributes
            if attribute_name in self.raw_check_list_nvme:
                try:
                    raw_value_int = int(raw_value, 0)  # Handle hex values
                except ValueError:
                    continue
                
                if raw_value_int > 0:
                    if attribute_name in self.warn_list and raw_value_int >= self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value_int})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value_int})")
                        self.escalate_status('WARNING')
                    elif attribute_name in self.warn_list and raw_value_int < self.warn_list[attribute_name]:
                        self.debug(f"{attribute_name} is non-zero ({raw_value_int}) but less than {self.warn_list[attribute_name]}")
                        notice_messages.append(f"{attribute_name} is non-zero ({raw_value_int}) (but less than threshold {self.warn_list[attribute_name]})")
                    else:
                        self.debug(f"{attribute_name} is non-zero ({raw_value_int})")
                        warning_messages.append(f"{attribute_name} is non-zero ({raw_value_int})")
                        self.escalate_status('WARNING')
                else:
                    self.debug(f"{attribute_name} is OK ({raw_value_int})")
            else:
                self.debug(f"{attribute_name} not in raw check list (raw value: {raw_value})")
        
        return perfdata
    
    def parse_scsi_attributes(self, output: List[str], error_messages: List[str],
                             warning_messages: List[str]) -> List[str]:
        """Parse SCSI SMART attributes"""
        perfdata = []
        current_temperature = None
        max_temperature = None
        current_start_stop = None
        max_start_stop = None
        
        for line in output:
            if 'Current Drive Temperature:' in line:
                match = re.search(r'Current Drive Temperature:\s+(\d+)', line)
                if match:
                    current_temperature = int(match.group(1))
            
            elif 'Drive Trip Temperature:' in line:
                match = re.search(r'Drive Trip Temperature:\s+(\d+)', line)
                if match:
                    max_temperature = int(match.group(1))
            
            elif 'Current start stop count:' in line:
                match = re.search(r'Current start stop count:\s+(\d+)', line)
                if match:
                    current_start_stop = int(match.group(1))
            
            elif 'Recommended maximum start stop count:' in line:
                match = re.search(r'Recommended maximum start stop count:\s+(\d+)', line)
                if match:
                    max_start_stop = int(match.group(1))
            
            elif 'Elements in grown defect list:' in line:
                match = re.search(r'Elements in grown defect list:\s+(\d+)', line)
                if match:
                    defectlist = int(match.group(1))
                    
                    if self.args.bad:
                        perfdata.append(f"defect_list={defectlist};{self.args.bad};{self.args.bad};;")
                        if defectlist > 0 and defectlist >= self.args.bad:
                            warning_messages.append(f"{defectlist} Elements in grown defect list (threshold {self.args.bad})")
                            self.escalate_status('WARNING')
                            self.debug(f"Elements in grown defect list is non-zero ({defectlist})")
                        elif defectlist > 0 and defectlist < self.args.bad:
                            warning_messages.append(f"Note: {defectlist} Elements in grown defect list")
                            self.debug(f"Elements in grown defect list is non-zero ({defectlist}) but less than {self.args.bad}")
                    else:
                        if defectlist > 0:
                            warning_messages.append(f"{defectlist} Elements in grown defect list")
                            self.escalate_status('WARNING')
                            self.debug(f"Elements in grown defect list is non-zero ({defectlist})")
                        if self.args.device:
                            perfdata.append(f"defect_list={defectlist};;;;")
            
            elif 'Blocks sent to initiator =' in line:
                match = re.search(r'Blocks sent to initiator =\s+(\d+)', line)
                if match and self.args.device:
                    perfdata.append(f"sent_blocks={match.group(1)};;;;")
        
        # Handle temperature
        if current_temperature is not None:
            if max_temperature is not None:
                if self.args.device:
                    perfdata.append(f"temperature={current_temperature};;{max_temperature};0;")
                if not self.args.skip_temp_check:
                    if current_temperature > max_temperature:
                        self.debug(f"Disk temperature is greater than max ({current_temperature} > {max_temperature})")
                        error_messages.append('Disk temperature is higher than maximum')
                        self.escalate_status('CRITICAL')
            else:
                if self.args.device:
                    perfdata.append(f"temperature={current_temperature};;;;")
        
        # Handle start/stop cycles
        if current_start_stop is not None:
            if max_start_stop is not None:
                if self.args.device:
                    perfdata.append(f"start_stop={current_start_stop};;;;{max_start_stop}")
                if current_start_stop > max_start_stop:
                    self.debug(f"Disk start_stop is greater than max ({current_start_stop} > {max_start_stop})")
                    warning_messages.append('Disk start_stop is higher than maximum')
                    self.escalate_status('WARNING')
            else:
                if self.args.device:
                    perfdata.append(f"start_stop={current_start_stop};;;;")
        
        return perfdata
    
    def run(self):
        """Main execution"""
        devices = self.get_devices()
        interfaces = self.expand_interface(self.args.interface)
        
        for device in devices:
            for interface in interfaces:
                self.check_device(device, interface)
        
        # Build final output
        self.debug(f"final status/output: {self.exit_status}")
        
        msg_list = []
        if self.drive_details:
            msg_list.append(self.drive_details)
        
        # Collect non-OK drives
        if self.drives_status_critical:
            self.drives_status_not_okay.extend(self.drives_status_critical)
        if self.drives_status_warning:
            self.drives_status_not_okay.extend(self.drives_status_warning)
        if self.drives_status_unknown:
            self.drives_status_not_okay.extend(self.drives_status_unknown)
        
        if self.drives_status_not_okay:
            msg_list.extend([x for x in self.drives_status_not_okay if x])
        
        if self.drives_status_not_okay and self.args.quiet and self.drives_status_okay:
            msg_list.append("Other drives OK")
        else:
            msg_list.extend([x for x in self.drives_status_okay if x])
        
        if self.args.debug:
            self.debug(f"drives  ok: {self.drives_status_okay}")
            self.debug(f"drives nok: {self.drives_status_not_okay}")
            self.debug(f"msg_list: {'^'.join(msg_list)}")
        
        separator = self.terminator if self.args.global_pattern else ' '
        self.status_string = separator.join(msg_list)
        
        # Final output
        print(f"{self.exit_status}: {self.status_string}|{self.perf_string}")
        sys.exit(ERRORS[self.exit_status])


def print_help():
    """Print help information"""
    help_text = f"""check_smart.py v{VERSION}
The monitoring plugins come with ABSOLUTELY NO WARRANTY. You may redistribute
copies of the plugins under the terms of the GNU General Public License.
For more information about these matters, see the file named COPYING.

Usage: check_smart.py {{-d=<block device>|-g=<block device glob>}} -i=(auto|ata|scsi|nvme|3ware,N|areca,N|hpt,L/M/N|aacraid,H,L,ID|cciss,N|megaraid,N|usbjmicron,N) [-r list] [-w list] [-b N] [-e list] [-E list] [-s] [-l] [--debug]

At least one of the below. -d supersedes -g
  -d/--device: a physical block device to be SMART monitored, eg /dev/sda. Pseudo-device /dev/bus/N is allowed.
  -g/--global: a glob pattern name of physical devices to be SMART monitored
       Example: '/dev/sd[a-z]' will search for all /dev/sda until /dev/sdz devices and report errors globally.
       Example: '/dev/sd*[a-z]' will search for all /dev/sda until /dev/sdzzzz etc devices and report errors globally.
       It is also possible to use -g in conjunction with megaraid devices. Example: -i 'megaraid,[0-3]'.
       Does not output performance data for historical value graphing.
Note that -g only works with a fixed interface (e.g. scsi, ata) and megaraid,N.

Other options
  -i/--interface: device's interface type (auto|ata|scsi|nvme|3ware,N|areca,N|hpt,L/M/N|aacraid,H,L,ID|cciss,N|megaraid,N|usbjmicron,N)
  (See http://www.smartmontools.org/wiki/Supported_RAID-Controllers for interface convention)
  -r/--raw Comma separated list of ATA or NVMe attributes to check
       ATA default: Current_Pending_Sector,Reallocated_Sector_Ct,Program_Fail_Cnt_Total,Uncorrectable_Error_Cnt,Offline_Uncorrectable,Runtime_Bad_Block,Reported_Uncorrect,Reallocated_Event_Count,Command_Timeout
       NVMe default: Media_and_Data_Integrity_Errors
  -b/--bad: Threshold value for Current_Pending_Sector for ATA and 'grown defect list' for SCSI drives
  -w/--warn Comma separated list of thresholds for ATA drives (e.g. Reallocated_Sector_Ct=10,Current_Pending_Sector=62)
  -e/--exclude: Comma separated list of SMART attribute names or numbers which should be excluded (=ignored) with regard to checks
  -E/--exclude-all: Comma separated list of SMART attribute names or numbers which should be completely ignored for checks as well as perfdata
  -s/--selftest: Enable self-test log check
  -l/--ssd-lifetime: Check attribute 'Percent_Lifetime_Remain' available on some SSD drives
  --skip-self-assessment: Skip SMART self-assessment health status check
  --skip-temp-check: Skip temperature comparison current vs. drive max temperature
  --skip-load-cycles: Do not alert on high load/unload cycle count (600K considered safe on hard drives)
  --skip-error-log: Do not alert on errors found in ATA log (ATA Error Count)
  --hide-sn: Do not show drive serial number in output
  -h/--help: this help
  -O/--oldage: Ignore old age attributes
  -q/--quiet: When faults detected, only show faulted drive(s) (only affects output when used with -g parameter)
  --debug: show debugging information
  -v/--version: Version number
"""
    print(help_text)


def main():
    parser = argparse.ArgumentParser(
        description='Check SMART status of ATA/SCSI/NVMe drives',
        add_help=False
    )
    
    parser.add_argument('-d', '--device', help='Block device to monitor')
    parser.add_argument('-g', '--global-pattern', dest='global_pattern', help='Glob pattern for devices')
    parser.add_argument('-i', '--interface', help='Device interface type')
    parser.add_argument('-b', '--bad', type=int, help='Threshold for bad sectors')
    parser.add_argument('-e', '--exclude', default='', help='Exclude attributes from checks')
    parser.add_argument('-E', '--exclude-all', dest='exclude_all', default='', help='Exclude attributes from checks and perfdata')
    parser.add_argument('-r', '--raw', help='Raw attributes to check')
    parser.add_argument('-w', '--warn', help='Warning thresholds')
    parser.add_argument('-s', '--selftest', action='store_true', help='Enable selftest log check')
    parser.add_argument('-l', '--ssd-lifetime', dest='ssd_lifetime', action='store_true', help='Check SSD lifetime')
    parser.add_argument('-O', '--oldage', action='store_true', help='Ignore old age attributes')
    parser.add_argument('-q', '--quiet', action='store_true', help='Only show faulted drives')
    parser.add_argument('--skip-self-assessment', dest='skip_self_assessment', action='store_true', help='Skip SMART self-assessment')
    parser.add_argument('--skip-temp-check', dest='skip_temp_check', action='store_true', help='Skip temperature check')
    parser.add_argument('--skip-load-cycles', dest='skip_load_cycles', action='store_true', help='Skip load cycle check')
    parser.add_argument('--skip-error-log', dest='skip_error_log', action='store_true', help='Skip error log check')
    parser.add_argument('--hide-sn', dest='hide_sn', action='store_true', help='Hide serial number')
    parser.add_argument('--debug', action='store_true', help='Debug output')
    parser.add_argument('-h', '--help', action='store_true', help='Show help')
    parser.add_argument('-v', '--version', action='store_true', help='Show version')
    
    args = parser.parse_args()
    
    if args.help:
        print_help()
        sys.exit(ERRORS['OK'])
    
    if args.version:
        print(f"check_smart.py v{VERSION}")
        print("The monitoring plugins come with ABSOLUTELY NO WARRANTY. You may redistribute")
        print("copies of the plugins under the terms of the GNU General Public License.")
        print("For more information about these matters, see the file named COPYING.")
        sys.exit(ERRORS['OK'])
    
    if not args.device and not args.global_pattern:
        print("UNKNOWN - Must specify a device!\n")
        print_help()
        sys.exit(ERRORS['UNKNOWN'])
    
    if not args.interface:
        print("must specify an interface using -i/--interface!\n")
        print_help()
        sys.exit(ERRORS['UNKNOWN'])
    
    # Validate interface
    valid_interfaces = r'^(ata|scsi|3ware|areca|hpt|aacraid|cciss|megaraid|sat|auto|nvme|usbjmicron)'
    if not re.match(valid_interfaces, args.interface):
        print(f"invalid interface {args.interface}!\n")
        print_help()
        sys.exit(ERRORS['UNKNOWN'])
    
    # Run check
    checker = SmartCheck(args)
    checker.run()


if __name__ == '__main__':
    main()
