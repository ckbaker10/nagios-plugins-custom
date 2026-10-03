#!/usr/bin/env python3
"""
Nagios Plugin for TP-Link P110 Smart Plug Monitoring
Checks device status, energy usage, and connectivity.

Supports both Passthrough and KLAP protocols for newer devices.

Dependencies:
- pycryptodome
- requests
- pkcs7

Copyright (C) 2024 - Based on PyP100 library with KLAP protocol support
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
import logging
import time
import traceback
import secrets
import struct
from typing import Optional, Dict, Any

# Suppress requests warnings
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging to suppress debug messages unless explicitly enabled
logging.getLogger().setLevel(logging.WARNING)

try:
    import requests
    from requests import Session
    from base64 import b64encode, b64decode
    import hashlib
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import AES, PKCS1_v1_5
    from Crypto.Util.Padding import pad, unpad
    import pkcs7
    import uuid
except ImportError as e:
    print(f"UNKNOWN - Missing required Python module: {e}")
    sys.exit(3)

# Nagios exit codes
NAGIOS_OK = 0
NAGIOS_WARNING = 1
NAGIOS_CRITICAL = 2
NAGIOS_UNKNOWN = 3


class TpLinkCipher:
    """Encryption/decryption for TP-Link Passthrough protocol"""
    def __init__(self, b_arr: bytearray, b_arr2: bytearray):
        self.iv = b_arr2
        self.key = b_arr

    def encrypt(self, data):
        data = pkcs7.PKCS7Encoder().encode(data)
        cipher = AES.new(bytes(self.key), AES.MODE_CBC, bytes(self.iv))
        encrypted = cipher.encrypt(data.encode("UTF-8"))
        return b64encode(encrypted).decode("UTF-8").replace("\r\n", "")

    def decrypt(self, data: str):
        aes = AES.new(bytes(self.key), AES.MODE_CBC, bytes(self.iv))
        pad_text = aes.decrypt(b64decode(data.encode("UTF-8"))).decode("UTF-8")
        return pkcs7.PKCS7Encoder().decode(pad_text)


class KlapCipher:
    """Encryption/decryption for TP-Link KLAP protocol"""
    def __init__(self, local_seed: bytes, remote_seed: bytes, user_hash: bytes):
        # Derive keys from seeds
        local_hash = local_seed + remote_seed + user_hash
        
        self.key = self._key_derive(local_hash)
        self.iv, initial_seq = self._iv_derive(local_hash)
        self.sig = self._sig_derive(local_hash)
        self.seq = initial_seq  # Start with derived sequence number
    
    def _key_derive(self, data: bytes) -> bytes:
        return hashlib.sha256(b"lsk" + data).digest()[:16]
    
    def _iv_derive(self, data: bytes) -> tuple[bytes, int]:
        hash_data = hashlib.sha256(b"iv" + data).digest()
        iv = hash_data[:12]
        seq = struct.unpack(">I", hash_data[-4:])[0]  # Last 4 bytes as big-endian i32
        return iv, seq
    
    def _sig_derive(self, data: bytes) -> bytes:
        return hashlib.sha256(b"ldk" + data).digest()[:28]
    
    def _iv_seq(self, seq: int) -> bytes:
        return self.iv + struct.pack(">I", seq)
    
    def encrypt(self, data: str) -> tuple[bytes, int]:
        # Increment sequence number BEFORE using it (like Rust fetch_add)
        self.seq += 1
        iv_seq = self._iv_seq(self.seq)
        
        cipher = AES.new(self.key, AES.MODE_CBC, iv_seq)
        encrypted = cipher.encrypt(pad(data.encode('utf-8'), AES.block_size))
        
        # Create signature
        sig_data = self.sig + struct.pack(">I", self.seq) + encrypted
        signature = hashlib.sha256(sig_data).digest()
        
        return signature + encrypted, self.seq
    
    def decrypt(self, seq: int, data: bytes, verbose=False) -> str:
        if verbose:
            print(f"DEBUG: Decrypt input - seq: {seq}, data length: {len(data)}")
            print(f"DEBUG: Decrypt input - data hex: {data.hex()}")
        
        if len(data) < 32:
            raise ValueError("Data too short for KLAP decryption")
        
        signature = data[:32]
        encrypted = data[32:]
        
        if verbose:
            print(f"DEBUG: Received signature: {signature.hex()}")
            print(f"DEBUG: Encrypted data: {encrypted.hex()}")
        
        # Verify signature
        sig_data = self.sig + struct.pack(">I", seq) + encrypted
        expected_sig = hashlib.sha256(sig_data).digest()
        
        if verbose:
            print(f"DEBUG: Sig data for verification: {sig_data.hex()}")
            print(f"DEBUG: Expected signature: {expected_sig.hex()}")
            print(f"DEBUG: Received signature: {signature.hex()}")
        
        if signature != expected_sig:
            if verbose:
                print("DEBUG: Signature verification failed!")
            raise ValueError("Invalid signature")
        
        if verbose:
            print("DEBUG: Signature verification passed")
        
        iv_seq = self._iv_seq(seq)
        cipher = AES.new(self.key, AES.MODE_CBC, iv_seq)
        decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
        
        return decrypted.decode('utf-8')


class P100:
    """TP-Link P100/P110 Smart Plug Controller with Protocol Discovery"""
    
    ERROR_CODES = {
        "0": "Success",
        "-1010": "Invalid Public Key Length",
        "-1012": "Invalid terminalUUID", 
        "-1501": "Invalid Request or Credentials",
        "1002": "Incorrect Request",
        "1003": "JSON formatting error - Invalid request format",
        "-1003": "JSON formatting error"
    }

    def __init__(self, ip_address: str, email: str, password: str):
        self.ipAddress = ip_address
        self.email = email
        self.password = password
        self.session = None
        self.errorCodes = self.ERROR_CODES
        
        # Protocol-specific variables
        self.protocol = None  # Will be set to 'passthrough' or 'klap'
        
        # Passthrough protocol variables
        self.terminalUUID = str(uuid.uuid4())
        self.cookie_name = "TP_SESSIONID"
        self.cookie = None
        self.token = None
        self.tpLinkCipher = None
        
        # KLAP protocol variables
        self.klap_cookie = None
        self.klapCipher = None
        
        # Initialize based on protocol discovery
        self.encryptCredentials()
        self.createKeyPair()

    def encryptCredentials(self):
        """Encrypt email and password for authentication"""
        self.encodedPassword = b64encode(self.password.encode("UTF-8")).decode("UTF-8")
        self.encodedEmail = self.sha_digest_username(self.email)
        self.encodedEmail = b64encode(self.encodedEmail.encode("utf-8")).decode("UTF-8")

    def createKeyPair(self):
        """Generate RSA key pair for handshake"""
        self.keys = RSA.generate(1024)
        self.privateKey = self.keys.exportKey("PEM")
        self.publicKey = self.keys.publickey().exportKey("PEM")

    def sha_digest_username(self, data):
        """Create SHA1 digest of username"""
        b_arr = data.encode("UTF-8")
        digest = hashlib.sha1(b_arr).digest()
        sb = ""
        for i in range(0, len(digest)):
            b = digest[i]
            hex_string = hex(b & 255).replace("0x", "")
            if len(hex_string) == 1:
                sb += "0" + hex_string
            else:
                sb += hex_string
        return sb

    def decode_handshake_key(self, key):
        """Decode the handshake key for cipher initialization"""
        decode = b64decode(key.encode("UTF-8"))
        cipher = PKCS1_v1_5.new(RSA.importKey(self.privateKey))
        do_final = cipher.decrypt(decode, None)
        if do_final is None:
            raise ValueError("Decryption failed!")

        b_arr = bytearray()
        b_arr2 = bytearray()

        for i in range(0, 16):
            b_arr.insert(i, do_final[i])
        for i in range(0, 16):
            b_arr2.insert(i, do_final[i + 16])

        return TpLinkCipher(b_arr, b_arr2)

    def discover_protocol(self, verbose=False):
        """Discover which protocol the device supports"""
        if verbose:
            print("DEBUG: Discovering protocol...")
        
        # Test passthrough protocol first
        try:
            response = self._test_passthrough_protocol(verbose)
            if verbose:
                print("DEBUG: Device supports Passthrough protocol")
            self.protocol = 'passthrough'
            return True
        except Exception as e:
            if verbose:
                print(f"DEBUG: Passthrough failed: {e}")
                print("DEBUG: Trying KLAP protocol...")
            
            # If passthrough fails, use KLAP
            self.protocol = 'klap'
            if verbose:
                print("DEBUG: Using KLAP protocol")
            return True
    
    def _test_passthrough_protocol(self, verbose=False):
        """Test if device supports passthrough protocol"""
        url = f"http://{self.ipAddress}/app"
        payload = {
            "method": "component_nego", 
            "params": {}
        }
        
        if self.session:
            self.session.close()
        self.session = Session()
        
        if verbose:
            print("DEBUG: Testing passthrough protocol...")
        
        response = self.session.post(url, json=payload, timeout=10)
        response_data = response.json()
        
        if verbose:
            print(f"DEBUG: Passthrough test response: {response_data}")
        
        if response_data.get("error_code") == 1003:
            raise Exception("Passthrough not supported (error 1003)")
        
        return response_data

    def klap_handshake(self, verbose=False):
        """Perform KLAP handshake"""
        if verbose:
            print("DEBUG: Starting KLAP handshake...")
            
        url = f"http://{self.ipAddress}"
        
        if self.session:
            self.session.close()
        self.session = Session()
        
        # Step 1: Generate local seed
        local_seed = secrets.token_bytes(16)
        
        if verbose:
            print(f"DEBUG: Local seed: {local_seed.hex()}")
        
        # Step 2: Send handshake1
        response1 = self.session.post(f"{url}/app/handshake1", data=local_seed, timeout=10)
        
        if response1.status_code != 200:
            raise Exception(f"Handshake1 failed with HTTP {response1.status_code}")
        
        remote_seed = response1.content[:16]
        server_hash = response1.content[16:]
        
        if verbose:
            print(f"DEBUG: Remote seed: {remote_seed.hex()}")
            print(f"DEBUG: Server hash: {server_hash.hex()}")
        
        # Step 3: Create auth hash and verify server hash
        username_hash = hashlib.sha1(self.email.encode()).digest()
        password_hash = hashlib.sha1(self.password.encode()).digest()
        auth_hash = hashlib.sha256(username_hash + password_hash).digest()
        
        expected_server_hash = hashlib.sha256(local_seed + remote_seed + auth_hash).digest()
        
        if verbose:
            print(f"DEBUG: Username hash: {username_hash.hex()}")
            print(f"DEBUG: Password hash: {password_hash.hex()}")
            print(f"DEBUG: Auth hash: {auth_hash.hex()}")
            print(f"DEBUG: Expected server hash: {expected_server_hash.hex()}")
            print(f"DEBUG: Received server hash: {server_hash.hex()}")
        
        if server_hash != expected_server_hash:
            raise Exception("Server hash verification failed")
        
        # Step 4: Send handshake2
        client_hash = hashlib.sha256(remote_seed + local_seed + auth_hash).digest()
        response2 = self.session.post(f"{url}/app/handshake2", data=client_hash, timeout=10)
        
        if response2.status_code != 200:
            raise Exception(f"Handshake2 failed with HTTP {response2.status_code}")
        
        # Step 5: Setup cipher 
        self.klapCipher = KlapCipher(local_seed, remote_seed, auth_hash)
        
        # Cookies should be automatically managed by the session
        if verbose:
            print(f"DEBUG: Available cookies from handshake1: {list(response1.cookies.keys())}")
            print(f"DEBUG: Session cookies after handshake: {dict(self.session.cookies)}")
        
        # Verify we have a session cookie  
        if not self.session.cookies:
            raise Exception("Failed to get session cookie from KLAP handshake")
        
        if verbose:
            print("DEBUG: KLAP handshake completed successfully")

    def handshake(self, verbose=False):
        """Perform handshake with protocol discovery"""
        # First discover which protocol to use
        if not self.protocol:
            self.discover_protocol(verbose)
        
        if self.protocol == 'passthrough':
            self._passthrough_handshake(verbose)
        elif self.protocol == 'klap':
            self.klap_handshake(verbose)
        else:
            raise Exception("Unknown protocol")
    
    def _passthrough_handshake(self, verbose=False):
        """Perform passthrough protocol handshake"""
        url = f"http://{self.ipAddress}/app"
        payload = {
            "method": "handshake",
            "params": {
                "key": self.publicKey.decode("utf-8"),
                "requestTimeMils": int(time.time() * 1000)
            }
        }
        
        if verbose:
            print(f"DEBUG: Passthrough handshake URL: {url}")
            print(f"DEBUG: Public key length: {len(self.publicKey)}")
            print(f"DEBUG: Handshake payload: {json.dumps(payload, indent=2)}")
        
        if self.session:
            self.session.close()
        self.session = Session()

        if verbose:
            print("DEBUG: Sending passthrough handshake request...")
        r = self.session.post(url, json=payload, timeout=10)
        
        if verbose:
            print(f"DEBUG: Handshake response status: {r.status_code}")
            print(f"DEBUG: Handshake response content: {r.text}")
        
        if r.status_code != 200:
            raise Exception(f"Handshake failed with HTTP {r.status_code}")
            
        response_data = r.json()
        if verbose:
            print(f"DEBUG: Handshake parsed JSON: {json.dumps(response_data, indent=2)}")
            
        if "error_code" in response_data and response_data["error_code"] != 0:
            error_code = response_data["error_code"]
            error_message = self.errorCodes.get(str(error_code), "Unknown error")
            raise Exception(f"Handshake error {error_code}: {error_message}")

        encrypted_key = response_data["result"]["key"]
        self.tpLinkCipher = self.decode_handshake_key(encrypted_key)

        try:
            self.cookie = f"{self.cookie_name}={r.cookies[self.cookie_name]}"
        except KeyError:
            raise Exception("Failed to get session cookie from handshake")

    def login(self, verbose=False):
        """Login to the device using appropriate protocol"""
        if self.protocol == 'passthrough':
            self._passthrough_login(verbose)
        elif self.protocol == 'klap':
            # KLAP doesn't need separate login, it's done in handshake
            if verbose:
                print("DEBUG: KLAP login completed during handshake")
        else:
            raise Exception("No protocol established")
    
    def _passthrough_login(self, verbose=False):
        """Login using passthrough protocol"""
        url = f"http://{self.ipAddress}/app"
        payload = {
            "method": "login_device",
            "params": {
                "password": self.encodedPassword,
                "username": self.encodedEmail
            },
            "requestTimeMils": int(time.time() * 1000),
        }
        
        if verbose:
            print(f"DEBUG: Passthrough login URL: {url}")
            print(f"DEBUG: Encoded email length: {len(self.encodedEmail)}") 
            print(f"DEBUG: Encoded password length: {len(self.encodedPassword)}")
            print(f"DEBUG: Cookie: {self.cookie}")
        
        headers = {"Cookie": self.cookie}

        encrypted_payload = self.tpLinkCipher.encrypt(json.dumps(payload))
        secure_passthrough_payload = {
            "method": "securePassthrough",
            "params": {"request": encrypted_payload}
        }

        r = self.session.post(url, json=secure_passthrough_payload, headers=headers, timeout=10)
        
        if r.status_code != 200:
            raise Exception(f"Login failed with HTTP {r.status_code}")
            
        decrypted_response = self.tpLinkCipher.decrypt(r.json()["result"]["response"])
        response_data = json.loads(decrypted_response)
        
        if response_data["error_code"] != 0:
            error_code = response_data["error_code"]
            error_message = self.errorCodes.get(str(error_code), "Unknown error")
            raise Exception(f"Login error {error_code}: {error_message}")
        
        self.token = response_data["result"]["token"]

    def get_device_info(self, verbose=False):
        """Get device information using appropriate protocol"""
        if self.protocol == 'passthrough':
            return self._passthrough_get_device_info()
        elif self.protocol == 'klap':
            return self._klap_get_device_info(verbose)
        else:
            raise Exception("No protocol established")
    
    def _passthrough_get_device_info(self):
        """Get device info using passthrough protocol"""
        url = f"http://{self.ipAddress}/app?token={self.token}"
        payload = {
            "method": "get_device_info",
            "requestTimeMils": int(time.time() * 1000),
        }
        headers = {"Cookie": self.cookie}

        encrypted_payload = self.tpLinkCipher.encrypt(json.dumps(payload))
        secure_passthrough_payload = {
            "method": "securePassthrough",
            "params": {"request": encrypted_payload}
        }

        r = self.session.post(url, json=secure_passthrough_payload, headers=headers, timeout=10)
        
        if r.status_code != 200:
            raise Exception(f"Get device info failed with HTTP {r.status_code}")
            
        decrypted_response = self.tpLinkCipher.decrypt(r.json()["result"]["response"])
        return json.loads(decrypted_response)
    
    def _klap_get_device_info(self, verbose=False):
        """Get device info using KLAP protocol"""
        payload = {
            "method": "get_device_info",
            "requestTimeMils": int(time.time() * 1000),
        }
        
        return self._klap_request(payload, verbose)
    
    def _klap_request(self, payload, verbose=False):
        """Make a KLAP request"""
        url = f"http://{self.ipAddress}"
        
        encrypted_data, seq = self.klapCipher.encrypt(json.dumps(payload))
        
        # Use the session's cookie jar instead of manual headers
        # The cookies should already be set from the handshake
        
        if verbose:
            print(f"DEBUG: KLAP request URL: {url}/app/request?seq={seq}")
            print(f"DEBUG: Session cookies: {dict(self.session.cookies)}")
            print(f"DEBUG: KLAP payload: {json.dumps(payload)}")
        
        # Don't set cookie headers manually, let the session handle it
        r = self.session.post(f"{url}/app/request?seq={seq}", 
                            data=encrypted_data, 
                            timeout=10)
        
        if verbose:
            print(f"DEBUG: KLAP response status: {r.status_code}")
            print(f"DEBUG: KLAP response headers: {dict(r.headers)}")
        
        if r.status_code != 200:
            raise Exception(f"KLAP request failed with HTTP {r.status_code}")
        
        decrypted_response = self.klapCipher.decrypt(seq, r.content, verbose)
        if verbose:
            print(f"DEBUG: KLAP decrypted response: {decrypted_response}")
        
        return json.loads(decrypted_response)


class P110(P100):
    """TP-Link P110 Smart Plug with Energy Monitoring"""

    def get_energy_usage(self):
        """Get energy usage data using appropriate protocol"""
        if self.protocol == 'passthrough':
            return self._passthrough_get_energy_usage()
        elif self.protocol == 'klap':
            return self._klap_get_energy_usage()
        else:
            raise Exception("No protocol established")
    
    def _passthrough_get_energy_usage(self):
        """Get energy usage using passthrough protocol"""
        url = f"http://{self.ipAddress}/app?token={self.token}"
        payload = {
            "method": "get_energy_usage",
            "requestTimeMils": int(time.time() * 1000),
        }
        headers = {"Cookie": self.cookie}

        encrypted_payload = self.tpLinkCipher.encrypt(json.dumps(payload))
        secure_passthrough_payload = {
            "method": "securePassthrough",
            "params": {"request": encrypted_payload}
        }

        r = self.session.post(url, json=secure_passthrough_payload, headers=headers, timeout=10)
        
        if r.status_code != 200:
            raise Exception(f"Get energy usage failed with HTTP {r.status_code}")
            
        decrypted_response = self.tpLinkCipher.decrypt(r.json()["result"]["response"])
        return json.loads(decrypted_response)
    
    def _klap_get_energy_usage(self, verbose=False):
        """Get energy usage using KLAP protocol"""
        payload = {
            "method": "get_energy_usage",
            "requestTimeMils": int(time.time() * 1000),
        }
        
        return self._klap_request(payload, verbose)


@contextlib.contextmanager
def device_lock(hostname, timeout):
    """Serialize checks of one plug on this host (one KLAP session per plug)."""
    path = os.path.join(tempfile.gettempdir(), f"check_p110-{re.sub(r'[^A-Za-z0-9.-]', '_', hostname)}.lock")
    with open(path, "a") as fh:
        try:
            os.chmod(path, 0o666)
        except OSError:
            pass
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"another check of {hostname} is still running")
                time.sleep(0.5)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def query_device(args):
    """Handshake, login and read device info and energy usage (one session)."""
    p110 = P110(args.hostname, args.email, args.password)
    if args.verbose:
        print(f"DEBUG: P110 object created with terminalUUID: {p110.terminalUUID}")
    p110.handshake(verbose=args.verbose)
    p110.login(verbose=args.verbose)
    device_info = p110.get_device_info(verbose=args.verbose)
    if args.verbose:
        print(f"DEBUG: Device info response: {json.dumps(device_info, indent=2)}")

    energy_data = None
    try:
        energy_info = p110.get_energy_usage()
        if energy_info["error_code"] == 0:
            energy_data = energy_info["result"]
    except Exception as e:
        # Energy usage might not be available on all models
        if args.verbose:
            print(f"DEBUG: Energy data not available: {e}")
    return device_info, energy_data


def check_p110_status(args) -> tuple:
    """Check P110 status and return Nagios result"""
    try:
        if args.verbose:
            print(f"DEBUG: Connecting to P110 at {args.hostname}")
            print(f"DEBUG: Using email: {args.email}")
            print(f"DEBUG: Timeout: {args.timeout}s")
        
        # A plug keeps only one KLAP session: a second handshake (e.g. the
        # tapo-stats and tapo-status-on services hitting the same plug at the
        # same time) invalidates the first one, which then fails with HTTP 403
        # or "Invalid signature". Checks of the same plug are therefore
        # serialized with a lock, and transient failures (also short WiFi
        # dropouts) are retried with a fresh handshake.
        with device_lock(args.hostname, args.lock_timeout):
            attempt = 0
            while True:
                attempt += 1
                try:
                    device_info, energy_data = query_device(args)
                    break
                except Exception as e:
                    if attempt > args.retries:
                        raise
                    if args.verbose:
                        print(f"DEBUG: attempt {attempt} failed ({e}), retrying in {args.retry_delay}s")
                    time.sleep(args.retry_delay)

        if device_info["error_code"] != 0:
            return NAGIOS_CRITICAL, f"Device error: {device_info.get('msg', 'Unknown error')}"

        device_result = device_info["result"]
        device_on = device_result.get("device_on", False)
        device_name = b64decode(device_result.get("nickname", "")).decode("utf-8") if device_result.get("nickname") else "Unknown"
        signal_level = device_result.get("signal_level", 0)
        rssi = device_result.get("rssi", 0)
        power_protection_status = device_result.get("power_protection_status", "unknown")
        overcurrent_status = device_result.get("overcurrent_status", "unknown")
        charging_status = device_result.get("charging_status", "unknown")

        if args.verbose:
            print(f"DEBUG: Device name: {device_name}")
            print(f"DEBUG: Device on: {device_on}")
            print(f"DEBUG: Signal level: {signal_level}")
            print(f"DEBUG: RSSI: {rssi}")

        # Build status message
        status_parts = []
        performance_data = []
        exit_code = NAGIOS_OK
        
        # Check device state
        if not device_on and args.expect_on:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append("DEVICE OFF")
        elif device_on and args.expect_off:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append("DEVICE ON (unexpected)")
        else:
            status_parts.append(f"Device: {'ON' if device_on else 'OFF'}")
        
        # Check signal strength
        if signal_level < args.signal_critical:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append(f"SIGNAL CRITICAL ({signal_level})")
        elif signal_level < args.signal_warning:
            exit_code = max(exit_code, NAGIOS_WARNING)
            status_parts.append(f"SIGNAL LOW ({signal_level})")
        
        performance_data.append(f"signal_level={signal_level};{args.signal_warning};{args.signal_critical}")
        performance_data.append(f"rssi={rssi}dBm")
        
        # Check status fields
        if args.expect_power_protection and power_protection_status != args.expect_power_protection:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append(f"POWER PROTECTION {power_protection_status.upper()} (expected {args.expect_power_protection})")
        
        if args.expect_overcurrent and overcurrent_status != args.expect_overcurrent:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append(f"OVERCURRENT {overcurrent_status.upper()} (expected {args.expect_overcurrent})")
        
        if args.expect_charging and charging_status != args.expect_charging:
            exit_code = max(exit_code, NAGIOS_CRITICAL)
            status_parts.append(f"CHARGING {charging_status.upper()} (expected {args.expect_charging})")
        
        # Process energy data if available
        if energy_data:
            current_power = energy_data.get("current_power", 0) / 1000.0  # Convert mW to W
            today_energy = energy_data.get("today_energy", 0)
            month_energy = energy_data.get("month_energy", 0)
            
            # Check power thresholds
            if args.power_critical and current_power > args.power_critical:
                exit_code = max(exit_code, NAGIOS_CRITICAL)
                status_parts.append(f"POWER CRITICAL ({current_power:.1f}W)")
            elif args.power_warning and current_power > args.power_warning:
                exit_code = max(exit_code, NAGIOS_WARNING)
                status_parts.append(f"POWER HIGH ({current_power:.1f}W)")
            
            performance_data.extend([
                f"power={current_power:.3f}W;{args.power_warning or ''};{args.power_critical or ''}",
                f"energy_today={today_energy}Wh",
                f"energy_month={month_energy}Wh"
            ])
            
            status_parts.append(f"Power: {current_power:.1f}W")
        
        # Build final status message
        if exit_code == NAGIOS_OK:
            status_prefix = "OK"
        elif exit_code == NAGIOS_WARNING:
            status_prefix = "WARNING"
        else:
            status_prefix = "CRITICAL"
        
        status_message = f"{status_prefix} - {device_name}: {' - '.join(status_parts)}"
        
        if performance_data:
            status_message += f" | {' '.join(performance_data)}"
        
        return exit_code, status_message
        
    except Exception as e:
        error_msg = f"Connection/Authentication failed: {str(e)}"
        if args.verbose:
            print(f"DEBUG: Exception occurred: {type(e).__name__}")
            print(f"DEBUG: Exception message: {str(e)}")
            print("DEBUG: Full traceback:")
            traceback.print_exc()
        return NAGIOS_CRITICAL, error_msg


def main():
    parser = argparse.ArgumentParser(
        description="Nagios plugin to monitor TP-Link P110 smart plugs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s -H 192.168.1.100 -u user@example.com -p password
  %(prog)s -H 192.168.1.100 -u user@example.com -p password --expect-on
  %(prog)s -H plug.local -u user@example.com -p password --power-warning 1000 --power-critical 1500
  %(prog)s -H 192.168.1.100 -u user@example.com -p password --signal-warning 2 --signal-critical 1 --timeout 5
  %(prog)s -H 192.168.1.100 -u user@example.com -p password --expect-power-protection normal --expect-overcurrent normal
        """
    )
    
    parser.add_argument(
        "-H", "--hostname",
        required=True,
        help="Hostname or IP address of the P110 smart plug"
    )
    
    parser.add_argument(
        "-u", "--email",
        required=True,
        help="TP-Link account email"
    )
    
    parser.add_argument(
        "-p", "--password", 
        required=True,
        help="TP-Link account password"
    )
    
    parser.add_argument(
        "-t", "--timeout", 
        type=int, 
        default=10,
        help="Connection timeout in seconds (default: 10)"
    )
    
    parser.add_argument(
        "--expect-on", 
        action="store_true",
        help="Expect device to be ON (CRITICAL if OFF)"
    )
    
    parser.add_argument(
        "--expect-off",
        action="store_true",
        help="Expect device to be OFF (CRITICAL if ON)"
    )
    
    parser.add_argument(
        "--power-warning",
        type=float,
        help="Power consumption warning threshold in Watts"
    )
    
    parser.add_argument(
        "--power-critical",
        type=float,
        help="Power consumption critical threshold in Watts"
    )
    
    parser.add_argument(
        "--signal-warning",
        type=int,
        default=2,
        help="Signal level warning threshold (default: 2)"
    )
    
    parser.add_argument(
        "--signal-critical",
        type=int,
        default=1,
        help="Signal level critical threshold (default: 1)"
    )
    
    parser.add_argument(
        "--expect-power-protection",
        choices=["normal", "over_power"],
        help="Expected power protection status (CRITICAL if different)"
    )
    
    parser.add_argument(
        "--expect-overcurrent",
        choices=["normal", "over_current"],
        help="Expected overcurrent status (CRITICAL if different)"
    )
    
    parser.add_argument(
        "--expect-charging",
        choices=["normal", "charging", "not_charging"],
        help="Expected charging status (CRITICAL if different)"
    )
    
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Retries with a fresh handshake after connection/session errors (default: 2)"
    )

    parser.add_argument(
        "--retry-delay",
        type=float,
        default=3,
        help="Seconds between retries (default: 3)"
    )

    parser.add_argument(
        "--lock-timeout",
        type=float,
        default=30,
        help="Max. seconds to wait for another check of the same plug (default: 30)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output for debugging"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.expect_on and args.expect_off:
        print("UNKNOWN - Cannot expect both ON and OFF states")
        sys.exit(NAGIOS_UNKNOWN)
    
    if (args.power_warning and args.power_critical and 
        args.power_warning >= args.power_critical):
        print("UNKNOWN - Power warning threshold must be less than critical threshold")
        sys.exit(NAGIOS_UNKNOWN)
    
    if args.signal_warning <= args.signal_critical:
        print("UNKNOWN - Signal warning threshold must be greater than critical threshold")
        sys.exit(NAGIOS_UNKNOWN)
    
    # Enable verbose logging if requested
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.basicConfig(level=logging.DEBUG)
    
    # Perform the check
    exit_code, message = check_p110_status(args)
    print(message)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()