#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tuya Smart Device Management Core Module - Cloud Development Mode (App Account Association)
Provides device list query, status query, control and other functions

Technical Solution: Cloud Development Mode + Associated App Account
- No user login required, directly use Access ID + Secret for authentication
- Supports two query methods:
  1. Via UID (TUYA_UID environment variable): source_type=tuyaUser
  2. Via Schema (TUYA_SCHEMA environment variable): source_type=homeApp (if UID is not set)
- Use /v1.3/iot-03/devices endpoint to get device list
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from tuya_connector import TuyaOpenAPI

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config_from_env_file():
    """
    Load configuration from config.env file

    Returns:
        Dictionary containing configuration items, returns empty dictionary if file does not exist
    """
    config = {}

    # Find config.env file (search upwards from current directory)
    current_dir = Path.cwd()
    search_dirs = [current_dir]

    # Add project root directory to search path (parent directory of skill directory)
    skill_dir = Path(__file__).parent.parent
    project_root = skill_dir.parent
    if project_root not in search_dirs:
        search_dirs.append(project_root)

    # Find config.env file
    env_file = None
    for dir_path in search_dirs:
        potential_file = dir_path / "config.env"
        if potential_file.exists():
            env_file = potential_file
            break

    if not env_file:
        logger.debug("config.env file not found, will use environment variables")
        return config

    logger.debug(f"Reading configuration file: {env_file}")

    try:
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE format
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes (if any)
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    config[key] = value
                    logger.debug(f"  Read config: {key}")

    except Exception as e:
        logger.warning(f"Failed to read config.env file: {str(e)}")

    return config


class TuyaDeviceManager:
    """
    Tuya Smart Device Manager - Cloud Development Mode

    Suitable for devices that have been associated to cloud projects via "Associate App Account"
    Supports querying devices via UID or Schema
    """

    def __init__(self, schema: str = None, uid: str = None):
        """
        Initialize device manager

        Args:
            schema: App channel identifier, if not provided read from config file or environment variable TUYA_SCHEMA
                   For example: smartlife (Smart Life App), tuyaSmart (Tuya Smart App), etc.
            uid: User UID, if not provided read from config file or environment variable TUYA_UID
                 Higher priority than schema, if UID is set then UID query is used
        """
        # Prefer loading configuration from config.env file, secondarily use environment variables
        file_config = load_config_from_env_file()

        self.access_id = file_config.get('TUYA_ACCESS_ID') or os.environ.get('TUYA_ACCESS_ID')
        self.access_secret = file_config.get('TUYA_ACCESS_SECRET') or os.environ.get('TUYA_ACCESS_SECRET')
        self.endpoint = file_config.get('TUYA_ENDPOINT') or os.environ.get(
            'TUYA_ENDPOINT',
            'https://openapi.tuyacn.com'
        )
        self.schema = schema or file_config.get('TUYA_SCHEMA') or os.environ.get('TUYA_SCHEMA')
        self.uid = uid or file_config.get('TUYA_UID') or os.environ.get('TUYA_UID')

        if not self.access_id or not self.access_secret:
            raise ValueError(
                "Please set TUYA_ACCESS_ID and TUYA_ACCESS_SECRET in config.env file, "
                "or set environment variables TUYA_ACCESS_ID and TUYA_ACCESS_SECRET"
            )

        # If UID is set, prefer UID mode
        if self.uid:
            logger.info("Using UID mode to query devices")
        elif not self.schema:
            raise ValueError(
                "Please provide uid parameter, or set TUYA_UID in config.env,\n"
                "or provide schema parameter, or set TUYA_SCHEMA in config.env.\n"
                "You can also use environment variables TUYA_UID or TUYA_SCHEMA.\n"
                "UID has higher priority, recommend setting TUYA_UID"
            )

        self.openapi = TuyaOpenAPI(
            self.endpoint,
            self.access_id,
            self.access_secret
        )
        self._connect()

    def _connect(self):
        """Establish API connection"""
        try:
            self.openapi.connect()
            if self.uid:
                logger.info(f"✅ Successfully connected to Tuya IoT platform (UID mode)")
            else:
                logger.info(f"✅ Successfully connected to Tuya IoT platform (schema: {self.schema})")
        except Exception as e:
            logger.error(f"❌ Connection failed: {str(e)}")
            raise

    def get_app_info(self) -> Optional[Dict[str, Any]]:
        """
        Get App application information

        Returns:
            App information dictionary, including name, Logo, description, etc.
        """
        try:
            response = self.openapi.get(f"/v1.0/apps/{self.schema}")
            if response.get('success'):
                return response.get('result', {})
            else:
                logger.warning(f"Failed to get App information: {response.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Exception getting App information: {str(e)}")
            return None

    def list_devices(self, page_size: int = 100) -> List[Dict[str, Any]]:
        """
        Get device list

        Preferably use UID mode (if TUYA_UID is set), otherwise use Schema mode

        Args:
            page_size: Number of devices per page, default 100

        Returns:
            Device list, each device contains id, name, category_name and other information
        """
        try:
            if self.uid:
                # Use UID mode (source_type=tuyaUser)
                logger.debug("Using UID mode to query devices")
                response = self.openapi.get(
                    "/v1.3/iot-03/devices",
                    {
                        "source_type": "tuyaUser",
                        "source_id": self.uid,
                        "page_size": page_size
                    }
                )
            else:
                # Use Schema mode (source_type=homeApp)
                logger.debug(f"Using Schema mode to query devices (schema: {self.schema})")
                response = self.openapi.get(
                    "/v1.3/iot-03/devices",
                    {
                        "source_type": "homeApp",
                        "source_id": self.schema,
                        "page_size": page_size
                    }
                )

            if response.get('success'):
                devices = response.get('result', {}).get('list', [])
                total = response.get('result', {}).get('total', 0)
                logger.info(f"📱 Found {len(devices)} device(s) (Total: {total})")
                return devices
            else:
                error_msg = response.get('msg', 'Unknown error')
                logger.error(f"Failed to get device list: {error_msg} {response}")
                return []
        except Exception as e:
            logger.error(f"Exception getting device list: {str(e)}")
            return []

    def get_homes(self) -> List[Dict[str, Any]]:
        """
        Get user's family list

        Call API: GET /v1.0/users/{uid}/homes

        Returns:
            Family list, each family contains home_id, name, room_list and other information
        """
        if not self.uid:
            logger.error("Getting family list requires UID, please set TUYA_UID environment variable")
            return []

        try:
            logger.debug(f"Using UID to query family list: {self.uid}")
            response = self.openapi.get(f"/v1.0/users/{self.uid}/homes")

            if response.get('success'):
                homes = response.get('result', [])
                logger.info(f"🏠 Found {len(homes)} family/families")
                return homes
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get family list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting family list: {str(e)}")
            return []

    def get_scenes(self, home_id: str) -> List[Dict[str, Any]]:
        """
        Get scene list for specified family

        Call API: GET /v1.1/homes/{home_id}/scenes

        Args:
            home_id: Family ID

        Returns:
            Scene list, each scene contains scene_id, name, enabled, actions and other information
        """
        try:
            logger.debug(f"Querying scene list for family {home_id}")
            response = self.openapi.get(f"/v1.1/homes/{home_id}/scenes")

            if response.get('success'):
                scenes = response.get('result', [])
                logger.info(f"🎬 Found {len(scenes)} scene(s) (Family ID: {home_id})")
                return scenes
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get scene list: {error_msg} (code: {error_code}) ${response}")
                return []
        except Exception as e:
            logger.error(f"Exception getting scene list: {str(e)}")
            return []

    def get_automations(self, home_id: str) -> List[Dict[str, Any]]:
        """
        Get automation list for specified family

        Call API: GET /v1.0/homes/{home_id}/automations

        Args:
            home_id: Family ID

        Returns:
            Automation list, each automation contains automation_id, name, enabled, conditions, actions and other information
        """
        try:
            logger.debug(f"Querying automation list for family {home_id}")
            response = self.openapi.get(f"/v1.0/homes/{home_id}/automations")

            if response.get('success'):
                automations = response.get('result', [])
                logger.info(f"🤖 Found {len(automations)} automation(s) (Family ID: {home_id})")
                return automations
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get automation list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting automation list: {str(e)}")
            return []

    def add_automation(self, home_id: str, automation_data: Dict[str, Any]) -> Optional[str]:
        """
        Add automation

        Call API: POST /v1.0/homes/{home_id}/automations

        Args:
            home_id: Family ID
            automation_data: Automation data, including:
                - name: Automation name
                - conditions: Condition array
                - actions: Action array
                - background: Background image (optional)
                - match_type: Condition match type (optional, default 1)

        Returns:
            Returns automation_id on success, None on failure
        """
        try:
            logger.debug(f"Adding automation to family {home_id}")
            logger.debug(f"Automation data: {json.dumps(automation_data, ensure_ascii=False)}")

            response = self.openapi.post(
                f"/v1.0/homes/{home_id}/automations",
                automation_data
            )

            if response.get('success'):
                automation_id = response.get('result', '')
                logger.info(f"✅ Automation added successfully (ID: {automation_id})")
                return automation_id
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to add automation: {error_msg} (code: {error_code})")
                return None
        except Exception as e:
            logger.error(f"Exception adding automation: {str(e)}")
            return None

    def enable_automation(self, home_id: str, automation_id: str) -> bool:
        """
        Enable automation

        Call API: PUT /v1.0/homes/{home_id}/automations/{automation_id}/actions/enable

        Args:
            home_id: Family ID
            automation_id: Automation ID

        Returns:
            Returns True on success, False on failure
        """
        try:
            logger.debug(f"Enabling automation {automation_id} (Family ID: {home_id})")
            response = self.openapi.put(
                f"/v1.0/homes/{home_id}/automations/{automation_id}/actions/enable"
            )

            if response.get('success'):
                logger.info(f"✅ Automation enabled (ID: {automation_id})")
                return True
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to enable automation: {error_msg} (code: {error_code})")
                return False
        except Exception as e:
            logger.error(f"Exception enabling automation: {str(e)}")
            return False

    def disable_automation(self, home_id: str, automation_id: str) -> bool:
        """
        Disable automation

        Call API: PUT /v1.0/homes/{home_id}/automations/{automation_id}/actions/disable

        Args:
            home_id: Family ID
            automation_id: Automation ID

        Returns:
            Returns True on success, False on failure
        """
        try:
            logger.debug(f"Disabling automation {automation_id} (Family ID: {home_id})")
            response = self.openapi.put(
                f"/v1.0/homes/{home_id}/automations/{automation_id}/actions/disable"
            )

            if response.get('success'):
                logger.info(f"✅ Automation disabled (ID: {automation_id})")
                return True
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to disable automation: {error_msg} (code: {error_code})")
                return False
        except Exception as e:
            logger.error(f"Exception disabling automation: {str(e)}")
            return False

    def delete_automation(self, home_id: str, automation_id: str) -> bool:
        """
        Delete automation

        Call API: DELETE /v1.0/homes/{home_id}/automations/{automation_id}

        Args:
            home_id: Family ID
            automation_id: Automation ID

        Returns:
            Returns True on success, False on failure
        """
        try:
            logger.debug(f"Deleting automation {automation_id} (Family ID: {home_id})")
            response = self.openapi.delete(
                f"/v1.0/homes/{home_id}/automations/{automation_id}"
            )

            if response.get('success'):
                logger.info(f"✅ Automation deleted (ID: {automation_id})")
                return True
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to delete automation: {error_msg} (code: {error_code})")
                return False
        except Exception as e:
            logger.error(f"Exception deleting automation: {str(e)}")
            return False

    def get_family_devices(self, home_id: str) -> List[Dict[str, Any]]:
        """
        Get device list for specified family

        Call API: GET /v1.0/homes/{home_id}/devices

        Args:
            home_id: Family ID

        Returns:
            Device list, each device contains id, name, product_name, online, status and other information
        """
        try:
            logger.debug(f"Querying device list for family {home_id}")
            response = self.openapi.get(f"/v1.0/homes/{home_id}/devices")

            if response.get('success'):
                devices = response.get('result', [])
                logger.info(f"📱 Found {len(devices)} device(s) (Family ID: {home_id})")
                return devices
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get family device list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting family device list: {str(e)}")
            return []

    def get_family_rooms(self, home_id: str) -> List[Dict[str, Any]]:
        """
        Get room list for specified family

        Call API: GET /v1.0/homes/{home_id}/rooms

        Args:
            home_id: Family ID

        Returns:
            Room list, each room contains room_id, name and other information
        """
        try:
            logger.debug(f"Querying detailed information for family {home_id}")
            response = self.openapi.get(f"/v1.0/homes/{home_id}/rooms")

            if response.get('success'):
                home_info = response.get('result', {})
                # Actual field name is rooms not room_list
                rooms = home_info.get('rooms', [])
                logger.info(f"🏠 Found {len(rooms)} room(s) (Family ID: {home_id})")
                return rooms
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get room list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting room list: {str(e)}")
            return []

    def get_user_devices(self) -> List[Dict[str, Any]]:
        """
        Get user's device list

        Call API: GET /v1.0/users/{uid}/devices

        Returns:
            Device list, each device contains id, name, product_name, online, status and other information
        """
        if not self.uid:
            logger.error("Getting device list requires UID, please set TUYA_UID environment variable")
            return []

        try:
            logger.debug(f"Using UID to query device list: {self.uid}")
            response = self.openapi.get(f"/v1.0/users/{self.uid}/devices")

            if response.get('success'):
                devices = response.get('result', [])
                logger.info(f"📱 Found {len(devices)} device(s)")
                return devices
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get device list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting device list: {str(e)}")
            return []

    def get_device_info(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get device detailed information

        Args:
            device_id: Device ID

        Returns:
            Device detailed information dictionary
        """
        try:
            response = self.openapi.get(f"/v1.0/devices/{device_id}")
            if response.get('success'):
                return response.get('result', {})
            else:
                logger.error(f"Failed to get device information: {response.get('msg')}")
                return None
        except Exception as e:
            logger.error(f"Exception getting device information: {str(e)}")
            return None

    def get_device_status(self, device_id: str) -> List[Dict[str, Any]]:
        """
        Get device current status

        Args:
            device_id: Device ID

        Returns:
            Device status list, each status contains code and value
        """
        try:
            response = self.openapi.get(f"/v1.0/devices/{device_id}/status")
            if response.get('success'):
                return response.get('result', [])
            else:
                logger.error(f"Failed to get device status: {response.get('msg')}")
                return []
        except Exception as e:
            logger.error(f"Exception getting device status: {str(e)}")
            return []

    def control_device(
        self,
        device_id: str,
        dp_code: str,
        dp_value: Any
    ) -> bool:
        """
        Control device

        Args:
            device_id: Device ID
            dp_code: DP instruction code, such as switch_1, bright_value, etc.
            dp_value: DP instruction value

        Returns:
            Whether the operation was successful
        """
        try:
            commands = {
                "commands": [{"code": dp_code, "value": dp_value}]
            }

            response = self.openapi.post(
                f"/v1.0/iot-03/devices/{device_id}/commands",
                commands
            )

            if response.get('success'):
                logger.info(f"✅ Device {device_id} control successful: {dp_code}={dp_value}")
                return True
            else:
                logger.error(f"❌ Device control failed: {response.get('msg')} {response}")
                return False
        except Exception as e:
            logger.error(f"Exception controlling device: {str(e)}")
            return False

    def turn_on(self, device_id: str, switch_code: str = "switch_1") -> bool:
        """Turn on device"""
        return self.control_device(device_id, switch_code, True)

    def turn_off(self, device_id: str, switch_code: str = "switch_1") -> bool:
        """Turn off device"""
        return self.control_device(device_id, switch_code, False)

    def set_brightness(self, device_id: str, brightness: int) -> bool:
        """Set device brightness (for light devices)"""
        if not 1 <= brightness <= 100:
            logger.error("Brightness value must be between 1-100")
            return False
        return self.control_device(device_id, "bright_value", brightness)

    def set_temperature(self, device_id: str, temperature: int) -> bool:
        """Set temperature (for temperature control devices)"""
        return self.control_device(device_id, "temp_set", temperature)

    def find_devices_by_name(self, name_pattern: str) -> List[Dict[str, Any]]:
        """Search for devices by name"""
        devices = self.get_user_devices()
        matched = [
            d for d in devices
            if name_pattern.lower() in d.get('name', '').lower()
        ]
        return matched

    def batch_control(
        self,
        device_ids: List[str],
        dp_code: str,
        dp_value: Any
    ) -> Dict[str, bool]:
        """Batch control multiple devices"""
        results = {}
        for device_id in device_ids:
            result = self.control_device(device_id, dp_code, dp_value)
            results[device_id] = result
        return results

    def get_device_functions(self, device_id: str) -> Dict[str, Any]:
        """
        Get function set for specified device

        Call API: GET /v1.0/devices/{device_id}/functions

        Args:
            device_id: Device ID

        Returns:
            Device function set information, including category and function list
            {
                "category": "kg",  # Category code
                "functions": [    # Function list
                    {
                        "name": "Switch",
                        "desc": "Main switch",
                        "code": "switch",
                        "type": "Boolean",
                        "values": "{}"
                    }
                ]
            }
        """
        try:
            logger.debug(f"Querying device function set: {device_id}")
            response = self.openapi.get(f"/v1.0/devices/{device_id}/functions")

            if response.get('success'):
                result = response.get('result', {})
                category = result.get('category', 'N/A')
                functions = result.get('functions', [])
                logger.info(f"📋 Device category: {category}, found {len(functions)} function(s)")
                return result
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get device function set: {error_msg} (code: {error_code})")
                return {}
        except Exception as e:
            logger.error(f"Exception getting device function set: {str(e)}")
            return {}

    def get_cities(self) -> List[Dict[str, Any]]:
        """
        Get city list

        Call API: GET /v1.0/iot-03/cities

        Returns:
            City list, each province contains province information and list of cities under it
        """
        try:
            logger.debug("Querying city list")
            response = self.openapi.get("/v1.0/iot-03/cities")

            if response.get('success'):
                cities = response.get('result', [])
                logger.info(f"🏙️ Found {len(cities)} province(s)")
                return cities
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get city list: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting city list: {str(e)}")
            return []

    def get_weather_conditions(self) -> List[Dict[str, Any]]:
        """
        Get weather conditions supported by automation

        Call API: GET /v1.0/homes/automation/weather/conditions

        Returns:
            Weather condition list, each condition contains category, name, operators and properties
        """
        try:
            logger.debug("Querying weather condition list")
            response = self.openapi.get("/v1.0/homes/automation/weather/conditions")

            if response.get('success'):
                conditions = response.get('result', [])
                logger.info(f"🌤️ Found {len(conditions)} weather condition(s)")
                return conditions
            else:
                error_msg = response.get('msg', 'Unknown error')
                error_code = response.get('code', 'N/A')
                logger.error(f"Failed to get weather conditions: {error_msg} (code: {error_code})")
                return []
        except Exception as e:
            logger.error(f"Exception getting weather conditions: {str(e)}")
            return []


# Convenience functions

def quick_turn_on(device_id: str) -> bool:
    """Quick turn on device"""
    manager = TuyaDeviceManager()
    return manager.turn_on(device_id)


def quick_turn_off(device_id: str) -> bool:
    """Quick turn off device"""
    manager = TuyaDeviceManager()
    return manager.turn_off(device_id)


def quick_list_devices() -> List[Dict[str, Any]]:
    """Quick get device list"""
    manager = TuyaDeviceManager()
    return manager.list_devices()


def quick_get_status(device_id: str) -> List[Dict[str, Any]]:
    """Quick get device status"""
    manager = TuyaDeviceManager()
    return manager.get_device_status(device_id)


if __name__ == "__main__":
    # Test code
    print("=" * 60)
    print("🏠 Tuya Smart Device Manager - Cloud Development Mode")
    print("=" * 60)
    print()
    print("Environment variable configuration:")
    print("  - TUYA_ACCESS_ID: Tuya Developer Platform Access ID")
    print("  - TUYA_ACCESS_SECRET: Tuya Developer Platform Access Secret")
    print("  - TUYA_SCHEMA: App channel identifier (important!)")
    print("      View in Tuya Developer Platform → App → App Management")
    print("      For example: smartlife (Smart Life App), oem_app_xxxxx (OEM App)")
    print("  - TUYA_ENDPOINT: API endpoint (optional, defaults to China region)")
    print()

    try:
        # Initialize manager
        manager = TuyaDeviceManager()

        # Display App information
        app_info = manager.get_app_info()
        if app_info:
            print(f"📱 App name: {app_info.get('name', 'N/A')}")
            print(f"🔑 Schema: {manager.schema}")
            print()

        # List all devices
        print("📱 Querying device list...")
        print("-" * 60)
        devices = manager.list_devices()

        if devices:
            print(f"\n✅ Found {len(devices)} device(s):\n")
            for i, device in enumerate(devices, 1):
                name = device.get('name', 'Unnamed')
                device_id = device.get('id', 'N/A')
                category = device.get('category_name', 'Unknown')
                category_code = device.get('category', 'N/A')
                online = device.get('online', False)
                product = device.get('product_name', 'N/A')

                print(f"{i}. {name}")
                print(f"   Device ID: {device_id}")
                print(f"   Category: {category} ({category_code})")
                print(f"   Status: {'🟢 Online' if online else '🔴 Offline'}")
                print(f"   Product: {product}")
                print()

            print("-" * 60)
            print(f"💡 Tip: You can use device ID to perform on/off control, status query and other operations")
            print(f"   Example: manager.turn_on('{devices[0].get('id')}')")
        else:
            print("\n❌ No devices found")
            print("\nPossible reasons:")
            print("1. No devices added to App")
            print("2. Devices not successfully associated to cloud development project")
            print("3. schema parameter is incorrect")
            print("4. Need to associate App account in 'Devices' page of Tuya Developer Platform")

    except ValueError as e:
        print(f"\n❌ Configuration error: {str(e)}")
        print("\nThere are two configuration methods:")
        print("\nCreate config.env file in project root directory (recommended)")
        print("  Create config.env file in project root directory with the following content:")
        print("  ```")
        print("  TUYA_ACCESS_ID=your-access-id")
        print("  TUYA_ACCESS_SECRET=your-access-secret")
        print("  TUYA_UID=your-uid")
        print("  TUYA_ENDPOINT=your data center endpoint (optional, default https://openapi.tuyacn.com)")
        print("  ```")
        print("How to get configuration information:")
        print("  1. TUYA_ACCESS_ID/SECRET: Login to Tuya Developer Platform https://platform.tuya.com/")
        print("     Enter your cloud project → Click avatar in top right → Access Key")
        print("  2. TUYA_UID: Open Tuya Smart App → Me → Click avatar → View UID")
    except Exception as e:
        print(f"\n❌ Runtime error: {str(e)}")
        import traceback
        traceback.print_exc()
