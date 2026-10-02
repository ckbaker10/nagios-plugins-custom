#!/usr/bin/env python3
"""
check_lm_sensors is a Nagios plugin to monitor the values of on board sensors and hard
disk temperatures on Linux systems

Copyright (c) 2007, ETH Zurich.
Converted to Python 2025.

This module is free software; you can redistribute it and/or modify it
under the terms of GNU general public license (gpl) version 3.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Dict, Optional, Tuple


__version__ = '3.2.0'


class SensorMonitor:
    """Main class for monitoring sensors and drive temperatures"""
    
    def __init__(self):
        self.verbosity = 0
        self.sensor_values: Dict[str, float] = {}
        self.checks: Dict[str, str] = {}
        self.highs: Dict[str, str] = {}
        self.lows: Dict[str, str] = {}
        self.ranges: Dict[str, str] = {}
        self.rename: Dict[str, str] = {}
        self.sanitize = False
        self.hddtemp_bin: Optional[str] = None
        self.sensors_bin: Optional[str] = None
        self.drives = True
        self.sensors = True
        self.list_mode = False
        self.timeout = 15
        
        # Status tracking
        self.criticals: list[str] = []
        self.warnings: list[str] = []
        self.unknowns: list[str] = []
        self.status_parts: list[str] = []
        self.desc_parts: list[str] = []
    
    def verbose(self, message: str, level: int = 0):
        """Print message if verbosity level is high enough"""
        if level < self.verbosity:
            print(message, end='')
    
    def get_path(self, program: str) -> Optional[str]:
        """Get the full path of a program using shutil.which"""
        return shutil.which(program)
    
    def parse_drives(self):
        """Parse /proc/partitions to find drives and get their temperatures"""
        if not self.hddtemp_bin or not os.path.isfile(self.hddtemp_bin) or not os.access(self.hddtemp_bin, os.X_OK):
            self.verbose("warning: hddtemp not found: HDD temperatures not checked\n")
            return
        
        self.verbose("Looking for drives in /proc/partitions\n")
        
        try:
            with open('/proc/partitions', 'r') as f:
                for line in f:
                    parts = line.strip().split()
                    
                    if len(parts) < 4:
                        continue
                    
                    major = parts[0]
                    if major == 'major' or major == '':
                        continue
                    
                    name = parts[3]
                    
                    # Skip partitions (devices ending in numbers)
                    if re.search(r'[0-9]$', name):
                        continue
                    
                    self.verbose(f"  checking disk /dev/{name}\n", 1)
                    
                    try:
                        result = subprocess.run(
                            ['sudo', self.hddtemp_bin, '-n', f'/dev/{name}'],
                            capture_output=True,
                            text=True,
                            timeout=self.timeout
                        )
                        
                        output = result.stdout.strip()
                        
                        if output and re.match(r'^[0-9]+$', output):
                            temp = int(output)
                            
                            sensor_name = f"{name}Temp" if self.sanitize else f"{name} Temp"
                            
                            # Check if sensor needs to be renamed
                            if sensor_name in self.rename:
                                sensor_name = self.rename[sensor_name]
                            
                            self.sensor_values[sensor_name] = float(temp)
                            
                            if self.verbosity or self.list_mode:
                                print(f"found temperature for drive {name} ({sensor_name} = {temp})")
                        else:
                            self.verbose(f"warning: temperature for /dev/{name} not available\n")
                    
                    # PermissionError: on timeout subprocess tries to kill the
                    # root-owned sudo process, which the nagios user may not
                    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
                        self.verbose(f"warning: temperature for /dev/{name} not available\n")
        
        except (IOError, OSError) as e:
            print(f"UNKNOWN: Cannot open /proc/partitions: {e}")
            sys.exit(3)
    
    def parse_sensors(self):
        """Retrieve values from lm_sensors using JSON output"""
        if not self.sensors_bin or not os.path.isfile(self.sensors_bin) or not os.access(self.sensors_bin, os.X_OK):
            self.verbose("warning: sensors not found: lm_sensors not checked\n")
            return
        
        # sensors reads /sys/class/hwmon, which is world-readable: no sudo, so
        # a hanging call (e.g. waking up a GPU for its temperature) can be
        # killed on timeout. One JSON call is enough.
        try:
            result = subprocess.run(
                [self.sensors_bin, '-Aj'],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
        except subprocess.TimeoutExpired:
            print(f"UNKNOWN: {self.sensors_bin} -Aj did not finish within {self.timeout}s")
            sys.exit(3)
        except OSError as e:
            print(f"UNKNOWN: cannot run {self.sensors_bin}: {e}")
            sys.exit(3)

        if result.returncode != 0 or not result.stdout.strip():
            self.verbose(f"warning: no sensor data: {result.stderr.strip()}\n")
            return

        try:
            data = json.loads(result.stdout)
            
            for chip_name, chip_data in data.items():
                for sensor_name, sensor_data in chip_data.items():
                    # Look for *_input or *_average fields
                    for field_name, field_value in sensor_data.items():
                        if field_name.endswith('_input') or field_name.endswith('_average'):
                            name = sensor_name
                            
                            if self.sanitize:
                                name = name.replace(' ', '')
                            
                            if name in self.rename:
                                name = self.rename[name]
                            
                            self.sensor_values[name] = float(field_value)
                            
                            if self.verbosity or self.list_mode:
                                print(f"found sensor {name} ({field_value})")
                            
                            break  # Only use the first *_input or *_average field
        
        except (json.JSONDecodeError, AttributeError, ValueError) as e:
            self.verbose(f"warning: could not parse sensor data: {e}\n")
    
    def get_sensor_value(self, name: str) -> Optional[float]:
        """Get sensor value, trying both with space and underscore"""
        if name in self.sensor_values:
            return self.sensor_values[name]
        
        converted_name = name.replace('_', ' ')
        if converted_name in self.sensor_values:
            return self.sensor_values[converted_name]
        
        return None
    
    def perform_checks(self):
        """Perform all configured checks"""
        
        # Old style checks (deprecated)
        for name, limits in self.checks.items():
            value = self.get_sensor_value(name)
            
            if value is None:
                self.unknowns.append(name)
                continue
            
            parts = limits.split(',')
            warn = float(parts[0])
            crit = float(parts[1])
            ref = float(parts[2]) if len(parts) > 2 else None
            
            diff = abs(value - ref) if ref is not None else value
            
            if diff > crit:
                self.criticals.append(f"{name}={value}")
            elif diff > warn:
                self.warnings.append(f"{name}={value}")
            
            self.status_parts.append(f"{name}={value};{warn};{crit};;")
            self.desc_parts.append(f"{name}={value}")
        
        # Low checks
        for name, limits in self.lows.items():
            value = self.get_sensor_value(name)
            
            if value is None:
                self.unknowns.append(name)
                continue
            
            parts = limits.split(',')
            warn = float(parts[0])
            crit = float(parts[1])
            
            if value < crit:
                self.criticals.append(f"{name}={value}")
            elif value < warn:
                self.warnings.append(f"{name}={value}")
            
            self.status_parts.append(f"{name}={value};{warn};{crit};;")
            self.desc_parts.append(f"{name}={value}")
        
        # High checks
        for name, limits in self.highs.items():
            value = self.get_sensor_value(name)
            
            if value is None:
                self.unknowns.append(name)
                continue
            
            parts = limits.split(',')
            warn = float(parts[0])
            crit = float(parts[1])
            
            if value > crit:
                self.criticals.append(f"{name}={value}")
            elif value > warn:
                self.warnings.append(f"{name}={value}")
            
            self.status_parts.append(f"{name}={value};{warn};{crit};;")
            self.desc_parts.append(f"{name}={value}")
        
        # Range checks
        for name, limits in self.ranges.items():
            value = self.get_sensor_value(name)
            
            if value is None:
                self.unknowns.append(name)
                continue
            
            parts = limits.split(',')
            warn = float(parts[0])
            crit = float(parts[1])
            ref = float(parts[2])
            
            diff = abs(value - ref)
            
            if diff > crit:
                self.criticals.append(f"{name}={value}")
            elif diff > warn:
                self.warnings.append(f"{name}={value}")
            
            self.status_parts.append(f"{name}={value};{warn};{crit};;")
            self.desc_parts.append(f"{name}={value}")
    
    def exit_with_status(self):
        """Exit with appropriate Nagios status code"""
        desc = ' '.join(self.desc_parts)
        status = ' '.join(self.status_parts)
        output = f"{desc}|{status}" if status else desc
        
        if self.criticals:
            print(f"CRITICAL: {output}")
            sys.exit(2)
        
        if self.warnings:
            print(f"WARNING: {output}")
            sys.exit(1)
        
        if self.unknowns:
            print(f"UNKNOWN: {output}")
            sys.exit(3)
        
        print(f"OK: {output}")
        sys.exit(0)


def parse_dict_arg(value: str) -> Tuple[str, str]:
    """Parse key=value argument"""
    if '=' not in value:
        raise argparse.ArgumentTypeError(f"Invalid format: {value}. Expected key=value")
    key, val = value.split('=', 1)
    return (key, val)


def main():
    parser = argparse.ArgumentParser(
        description='Check lm_sensors and drive temperatures',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --high temp1=50,60 --high temp2=50,60
  %(prog)s --low fan1=2000,1000
  %(prog)s --range v1=1,2,12
  %(prog)s --high temp1=50,60 --rename cputemp=temp1

Sensors with spaces in names can be specified:
  --high 'sda Temp'=50,60
  --high sda_Temp=50,60
  --sanitize --high sdaTemp=50,60
"""
    )
    
    parser.add_argument('-v', '--verbose', action='count', default=0,
                        help='Verbose output (can be specified multiple times)')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}')
    parser.add_argument('--list', action='store_true',
                        help='List all available sensors')
    
    # Check options
    parser.add_argument('-c', '--check', action='append', type=parse_dict_arg, default=[],
                        help='Check sensor (deprecated, use --high or --range)')
    parser.add_argument('--high', action='append', type=parse_dict_arg, default=[],
                        help='Check for high values: sensor=warn,crit')
    parser.add_argument('-l', '--low', action='append', type=parse_dict_arg, default=[],
                        help='Check for low values: sensor=warn,crit')
    parser.add_argument('-r', '--range', action='append', type=parse_dict_arg, default=[],
                        help='Check value range: sensor=warn,crit,reference')
    
    # Sensor options
    parser.add_argument('--rename', action='append', type=parse_dict_arg, default=[],
                        help='Rename sensor: newname=oldname')
    parser.add_argument('--sanitize', action='store_true',
                        help='Sanitize sensor names (remove spaces)')
    
    # Feature toggles
    parser.add_argument('--nosensors', action='store_true',
                        help='Disable lm_sensors checks')
    parser.add_argument('--nodrives', action='store_true',
                        help='Disable drive temperature checks')
    parser.add_argument('-d', '--drives', action='store_true',
                        help='Enable drive temperature checks (default)')
    
    # Binary paths
    parser.add_argument('--hddtemp_bin', type=str,
                        help='Path to hddtemp binary')
    parser.add_argument('--sensors_bin', type=str,
                        help='Path to sensors binary')
    parser.add_argument('-t', '--timeout', type=int, default=15,
                        help='Timeout in seconds for sensors/hddtemp calls (default: 15)')
    
    args = parser.parse_args()
    
    monitor = SensorMonitor()
    monitor.verbosity = args.verbose
    monitor.sanitize = args.sanitize
    monitor.list_mode = args.list
    monitor.timeout = args.timeout
    
    # Convert list of tuples to dicts
    monitor.checks = dict(args.check)
    monitor.highs = dict(args.high)
    monitor.lows = dict(args.low)
    monitor.ranges = dict(args.range)
    monitor.rename = dict(args.rename)
    
    # Feature flags
    monitor.drives = not args.nodrives
    monitor.sensors = not args.nosensors
    
    # Warn about deprecated option
    if monitor.checks:
        print("warning: the --check option is deprecated, use --low, --high, and --range instead")
    
    # Check that at least one check is specified
    if not args.list and not any([monitor.checks, monitor.highs, monitor.lows, monitor.ranges]):
        print("UNKNOWN: at least one check has to be specified")
        sys.exit(3)
    
    # Find binaries
    if monitor.drives:
        monitor.hddtemp_bin = args.hddtemp_bin or monitor.get_path('hddtemp')
        if monitor.hddtemp_bin:
            monitor.verbose(f"hddtemp found at {monitor.hddtemp_bin}\n")
        else:
            monitor.verbose("warning: hddtemp not found: HDD temperatures not checked\n")
    
    if monitor.sensors:
        monitor.sensors_bin = args.sensors_bin or monitor.get_path('sensors')
        if monitor.sensors_bin:
            monitor.verbose(f"sensors found at {monitor.sensors_bin}\n")
        else:
            monitor.verbose("warning: sensors not found: lm_sensors not checked\n")
    
    # Parse sensors
    if monitor.drives:
        monitor.parse_drives()
    
    if monitor.sensors:
        monitor.parse_sensors()
    
    # If list mode, exit here
    if args.list:
        sys.exit(0)
    
    # Perform checks
    monitor.perform_checks()
    
    # Exit with status
    monitor.exit_with_status()


if __name__ == '__main__':
    main()
