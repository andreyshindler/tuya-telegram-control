#!/usr/bin/env python3
"""
Tuya Smart Device Control CLI Tool
Provides a user-friendly CLI interface for controlling Tuya devices
"""

import argparse
import json
import sys
import os

# Add parent directory to path to import tuya_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.tuya_manager import TuyaDeviceManager


def print_devices(devices):
    """Format and print device list"""
    if not devices:
        print("\n❌ No devices found")
        return

    print(f"\n📱 Found {len(devices)} device(s):\n")
    print("-" * 60)

    for idx, device in enumerate(devices, 1):
        name = device.get('name', 'Unnamed')
        device_id = device.get('id', 'N/A')
        category = device.get('category_name', 'Unknown')
        online = device.get('online', False)
        status_icon = "🟢" if online else "🔴"

        print(f"  {idx}. {status_icon} {name}")
        print(f"     ID: {device_id}")
        print(f"     Type: {category}")
        print(f"     Status: {'Online' if online else 'Offline'}")
        print()


def print_status(status_list):
    """Format and print device status"""
    if not status_list:
        print("\n❌ Unable to get device status")
        return

    print("\n📊 Device Status:\n")
    print("-" * 40)

    for item in status_list:
        code = item.get('code', 'N/A')
        value = item.get('value', 'N/A')

        # Beautify display
        if isinstance(value, bool):
            value_str = "✅ ON" if value else "❌ OFF"
        else:
            value_str = str(value)

        print(f"  • {code}: {value_str}")
    print()


def cmd_list(manager, args):
    """List all devices"""
    devices = manager.list_devices()
    print_devices(devices)


def cmd_family_list(manager, args):
    """List family/house list"""
    homes = manager.get_homes()

    if not homes:
        print("\n❌ No families found")
        return

    print(f"\n🏠 Found {len(homes)} family/families:\n")
    print("=" * 60)

    for idx, home in enumerate(homes, 1):
        home_id = home.get('home_id', 'N/A')
        name = home.get('name', 'Unnamed')
        room_list = home.get('room_list', [])

        print(f"  {idx}. {name}")
        print(f"     ID: {home_id}")
        print(f"     Room count: {len(room_list)}")

        if room_list:
            print(f"     Room list:")
            for room in room_list:
                room_name = room.get('room_name', 'Unknown')
                device_count = len(room.get('device_list', []))
                print(f"       • {room_name} ({device_count} device(s))")

        print()


def cmd_scene_list(manager, args):
    """List scene list"""
    home_id = args.home_id
    scenes = manager.get_scenes(home_id)

    if not scenes:
        print(f"\n❌ No scenes found (Family ID: {home_id})")
        return

    print(f"\n🎬 Found {len(scenes)} scene(s):\n")
    print("=" * 60)

    for idx, scene in enumerate(scenes, 1):
        scene_id = scene.get('scene_id', 'N/A')
        name = scene.get('name', 'Unnamed')
        enabled = scene.get('enabled', False)
        status = scene.get('status', 'N/A')
        actions = scene.get('actions', [])

        print(f"  {idx}. {name}")
        print(f"     ID: {scene_id}")
        print(f"     Status: {'🟢 Enabled' if enabled else '🔴 Disabled'}")
        print(f"     Scene status: {status}")
        print(f"     Action count: {len(actions)}")

        if actions:
            print(f"     Action list:")
            for action in actions:
                action_name = action.get('action_name', 'Unknown action')
                executor = action.get('executor_name', 'N/A')
                entity_name = action.get('entity_name', 'N/A')
                print(f"       • {action_name} ({executor}) - {entity_name}")

        print()


def cmd_automations(manager, args):
    """List automation list"""
    home_id = args.home_id
    automations = manager.get_automations(home_id)

    if not automations:
        print(f"\n❌ No automations found (Family ID: {home_id})")
        return

    print(f"\n🤖 Found {len(automations)} automation(s):\n")
    print("=" * 60)

    for idx, automation in enumerate(automations, 1):
        automation_id = automation.get('automation_id', 'N/A')
        name = automation.get('name', 'Unnamed')
        enabled = automation.get('enabled', False)
        status = automation.get('status', 'N/A')
        conditions = automation.get('conditions', [])
        actions = automation.get('actions', [])

        print(f"  {idx}. {name}")
        print(f"     ID: {automation_id}")
        print(f"     Status: {'🟢 Enabled' if enabled else '🔴 Disabled'}")
        print(f"     Automation status: {status}")
        print(f"     Condition count: {len(conditions)}")
        print(f"     Action count: {len(actions)}")

        if conditions:
            print(f"     Trigger conditions:")
            for condition in conditions[:3]:  # Only show first 3 conditions
                cond_type = condition.get('display', {}).get('text', 'Unknown condition')
                print(f"       • {cond_type}")
            if len(conditions) > 3:
                print(f"       • ... ({len(conditions) - 3} more condition(s))")

        if actions:
            print(f"     Execution actions:")
            for action in actions[:3]:  # Only show first 3 actions
                action_name = action.get('action_name', 'Unknown action')
                executor_name = action.get('executor_name', 'N/A')
                entity_name = action.get('entity_name', 'N/A')
                print(f"       • {action_name} ({executor_name}) - {entity_name}")
            if len(actions) > 3:
                print(f"       • ... ({len(actions) - 3} more action(s))")

        print()


def cmd_add_automation(manager, args):
    """Add automation"""
    home_id = args.home_id

    # Read automation configuration from JSON file
    if args.json_file:
        try:
            with open(args.json_file, 'r', encoding='utf-8') as f:
                automation_data = json.load(f)
        except FileNotFoundError:
            print(f"\n❌ File not found: {args.json_file}")
            return
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON format error: {e}")
            return
    # Read from command line JSON string
    elif args.json:
        try:
            automation_data = json.loads(args.json)
        except json.JSONDecodeError as e:
            print(f"\n❌ JSON format error: {e}")
            return
    else:
        print("\n❌ Please provide automation configuration (--json or --json-file)")
        print("\nUsage examples:")
        print('  python scripts/tuya-cli.py add_automation 123456 --json \'{"name": "Test", "conditions": [], "actions": []}\'')
        print('  python scripts/tuya-cli.py add_automation 123456 --json-file automation.json')
        return

    # Validate required fields
    if 'name' not in automation_data:
        print("\n❌ Missing required field: name")
        return

    if 'conditions' not in automation_data:
        print("\n❌ Missing required field: conditions")
        return

    if 'actions' not in automation_data:
        print("\n❌ Missing required field: actions")
        return

    print(f"\n🔄 Adding automation '{automation_data['name']}' to family {home_id}...")
    print(f"Configuration: {json.dumps(automation_data, ensure_ascii=False, indent=2)}")

    automation_id = manager.add_automation(home_id, automation_data)

    if automation_id:
        print(f"\n✅ Automation added successfully!")
        print(f"   ID: {automation_id}")
        print(f"   Name: {automation_data['name']}")
    else:
        print("\n❌ Failed to add")


def cmd_automation_on(manager, args):
    """Enable automation"""
    home_id = args.home_id
    automation_id = args.automation_id

    print(f"\n🔄 Enabling automation {automation_id}...")
    result = manager.enable_automation(home_id, automation_id)

    if result:
        print("✅ Automation enabled")
    else:
        print("❌ Operation failed")


def cmd_automation_off(manager, args):
    """Disable automation"""
    home_id = args.home_id
    automation_id = args.automation_id

    print(f"\n🔄 Disabling automation {automation_id}...")
    result = manager.disable_automation(home_id, automation_id)

    if result:
        print("✅ Automation disabled")
    else:
        print("❌ Operation failed")


def cmd_automation_del(manager, args):
    """Delete automation"""
    home_id = args.home_id
    automation_id = args.automation_id

    print(f"\n🔄 Deleting automation {automation_id}...")
    result = manager.delete_automation(home_id, automation_id)

    if result:
        print("✅ Automation deleted")
    else:
        print("❌ Operation failed")


def cmd_family_devices(manager, args):
    """List devices for specified family"""
    home_id = args.home_id
    devices = manager.get_family_devices(home_id)

    if not devices:
        print(f"\n❌ No devices found (Family ID: {home_id})")
        return

    print(f"\n📱 Found {len(devices)} device(s) (Family ID: {home_id}):\n")
    print("=" * 60)

    for idx, device in enumerate(devices, 1):
        name = device.get('name', 'Unnamed')
        device_id = device.get('id', 'N/A')
        product_name = device.get('product_name', 'N/A')
        category = device.get('category', 'N/A')
        online = device.get('online', False)
        status = device.get('status', [])
        ip = device.get('ip', 'N/A')
        time_zone = device.get('time_zone', 'N/A')
        product_id = device.get('product_id', 'N/A')
        product_name = device.get('product_name', 'N/A')

        print(f"  {idx}. {name}")
        print(f"     ID: {device_id}")
        print(f"     Product: {product_name}")
        print(f"     Category: {category}")
        print(f"     Status: {str(online)+' desc: 🟢 Online' if online else '🔴 Offline'}")
        print(f"     IP: {ip}")
        print(f"     Timezone: {time_zone}")
        print(f"     Product ID: {product_id}")
        print(f"     Product Name: {product_name}")

        if status:
            print(f"     Current Status:")
            for item in status[:5]:  # Only show first 5 status items
                code = item.get('code', 'N/A')
                value = item.get('value', 'N/A')

                # Beautify display
                if isinstance(value, bool):
                    value_str = "✅ ON" if value else "❌ OFF"
                else:
                    value_str = str(value)
                # What type is value
                value_type = type(value).__name__

                print(f"       • dpCode:{code}  dpValue:{value}  dpValueType: {value_type}  desc: {value_str}")

        print()


def cmd_family_rooms(manager, args):
    """List rooms for specified family"""
    home_id = args.home_id
    rooms = manager.get_family_rooms(home_id)

    if not rooms:
        print(f"\n❌ No rooms found (Family ID: {home_id})")
        return

    print(f"\n🏠 Found {len(rooms)} room(s) (Family ID: {home_id}):\n")
    print("=" * 60)

    for idx, room in enumerate(rooms, 1):
        # Determine return data type
        if isinstance(room, str):
            # If room is string (room name)
            print(f"  {idx}. {room}")
        elif isinstance(room, dict):
            # If room is object (contains detailed information)
            room_id = room.get('room_id', 'N/A')
            name = room.get('name', 'Unnamed')
            device_count = room.get('device_count', 0)
            background = room.get('background', '')
            icon = room.get('icon', '')

            print(f"  {idx}. {name}")
            if room_id != 'N/A':
                print(f"     ID: {room_id}")
            print(f"     Device count: {device_count}")
            if icon:
                print(f"     Icon: {icon}")
            if background:
                print(f"     Background: {background}")

        print()


def cmd_devices(manager, args):
    """List user's device list"""
    devices = manager.get_user_devices()

    if not devices:
        print("\n❌ No devices found")
        return

    print(f"\n📱 Found {len(devices)} device(s):\n")
    print("=" * 60)

    for idx, device in enumerate(devices, 1):
        name = device.get('name', 'Unnamed')
        device_id = device.get('id', 'N/A')
        product_name = device.get('product_name', 'N/A')
        category = device.get('category', 'N/A')
        online = device.get('online', False)
        status = device.get('status', [])
        ip = device.get('ip', 'N/A')
        time_zone = device.get('time_zone', 'N/A')
        product_id = device.get('product_id', 'N/A')
        product_name = device.get('product_name', 'N/A')

        print(f"  {idx}. {name}")
        print(f"     ID: {device_id}")
        print(f"     Product: {product_name}")
        print(f"     Category: {category}")
        print(f"     Status: {str(online)+' desc: 🟢 Online' if online else '🔴 Offline'}")
        print(f"     IP: {ip}")
        print(f"     Timezone: {time_zone}")
        print(f"     Product ID: {product_id}")
        print(f"     Product Name: {product_name}")

        if status:
            print(f"     Current Status:")
            for item in status:
                code = item.get('code', 'N/A')
                value = item.get('value', 'N/A')

                # Beautify display
                if isinstance(value, bool):
                    value_str = "✅ ON" if value else "❌ OFF"
                else:
                    value_str = str(value)

                # What type is value
                value_type = type(value).__name__

                print(f"       • dpCode:{code}  dpValue:{value}  dpValueType: {value_type}  desc: {value_str}")

        print()


def cmd_on(manager, args):
    """Turn on device"""
    device_id = args.device_id
    switch_code = args.switch or "switch_1"

    print(f"\n🔄 Turning on device {device_id}...")
    result = manager.turn_on(device_id, switch_code)

    if result:
        print("✅ Device turned on")
    else:
        print(f"❌ Operation failed result: {result}")


def cmd_control(manager, args):
    """Control device"""
    device_id = args.device_id
    dp_code = args.dp_code
    # dp_value can be string, number, or boolean, try smart conversion
    dp_value = args.dp_value
    if isinstance(dp_value, str):
        if dp_value.lower() in ('true', 'false'):
            dp_value = dp_value.lower() == 'true'
        else:
            try:
                dp_value = int(dp_value)
            except ValueError:
                try:
                    dp_value = float(dp_value)
                except ValueError:
                    pass  # Keep as string

    print(f"\n🔄 Controlling device {device_id}...")
    result = manager.control_device(device_id, dp_code, dp_value)

    if result:
        print("✅ Control successful" f" dpCode: {dp_code} dpValue: {dp_value}")
    else:
        print(f"❌ Operation failed result: {result}")


def cmd_off(manager, args):
    """Turn off device"""
    device_id = args.device_id
    switch_code = args.switch or "switch_1"

    print(f"\n🔄 Turning off device {device_id}...")
    result = manager.turn_off(device_id, switch_code)

    if result:
        print("✅ Device turned off")
    else:
        print("❌ Operation failed")


def cmd_status(manager, args):
    """Query device status"""
    device_id = args.device_id

    print(f"\n🔄 Querying device {device_id} status...")
    status = manager.get_device_status(device_id)
    print_status(status)


def cmd_find(manager, args):
    """Find device by name"""
    name_pattern = args.name

    print(f"\n🔍 Searching for devices containing '{name_pattern}'...")
    devices = manager.find_devices_by_name(name_pattern)

    if devices:
        print(f"\n✅ Found {len(devices)} matching device(s):")
        print_devices(devices)
    else:
        print(f"\n❌ No devices found containing '{name_pattern}'")


def cmd_set(manager, args):
    """Set device DP value"""
    device_id = args.device_id
    dp_code = args.dp_code
    dp_value = args.dp_value

    # Try to convert value to appropriate type
    if dp_value.lower() in ('true', 'false'):
        dp_value = dp_value.lower() == 'true'
    else:
        try:
            dp_value = int(dp_value)
        except ValueError:
            try:
                dp_value = float(dp_value)
            except ValueError:
                pass  # Keep as string

    print(f"\n🔄 Setting device {device_id}: {dp_code}={dp_value}...")
    result = manager.control_device(device_id, dp_code, dp_value)

    if result:
        print(f"✅ Set successfully")
    else:
        print("❌ Set failed")


def cmd_brightness(manager, args):
    """Set device brightness"""
    device_id = args.device_id
    brightness = args.value

    print(f"\n🔄 Setting device {device_id} brightness to {brightness}%...")
    result = manager.set_brightness(device_id, brightness)

    if result:
        print(f"✅ Brightness set to {brightness}%")
    else:
        print("❌ Set failed")


def cmd_temp(manager, args):
    """Set device temperature"""
    device_id = args.device_id
    temperature = args.value

    print(f"\n🔄 Setting device {device_id} temperature to {temperature}°C...")
    result = manager.set_temperature(device_id, temperature)

    if result:
        print(f"✅ Temperature set to {temperature}°C")
    else:
        print("❌ Set failed")


def cmd_batch_on(manager, args):
    """Batch turn on devices"""
    device_ids = args.device_ids

    print(f"\n🔄 Batch turning on {len(device_ids)} device(s)...")
    results = manager.batch_control(device_ids, "switch_1", True)

    success_count = sum(1 for r in results.values() if r)
    print(f"\n✅ Success: {success_count}/{len(device_ids)}")


def cmd_batch_off(manager, args):
    """Batch turn off devices"""
    device_ids = args.device_ids

    print(f"\n🔄 Batch turning off {len(device_ids)} device(s)...")
    results = manager.batch_control(device_ids, "switch_1", False)

    success_count = sum(1 for r in results.values() if r)
    print(f"\n✅ Success: {success_count}/{len(device_ids)}")


def cmd_info(manager, args):
    """Get device detailed information"""
    device_id = args.device_id

    print(f"\n🔄 Getting device {device_id} information...")
    info = manager.get_device_info(device_id)

    if info:
        print("\n📋 Device Detailed Information:\n")
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print("❌ Get failed")


def cmd_cities(manager, args):
    """Query city list"""
    provinces = manager.get_cities()

    if not provinces:
        print("\n❌ No city information found")
        return

    print(f"\n🏙️ Found {len(provinces)} province(s):\n")
    print("=" * 60)

    for idx, province in enumerate(provinces, 1):
        province_id = province.get('id', 'N/A')
        province_name = province.get('name', 'Unnamed')
        cities = province.get('cities', [])

        print(f"  {idx}. {province_name}")
        print(f"     ID: {province_id}")
        print(f"     City count: {len(cities)}")

        if cities:
            print(f"     City list:")
            for city in cities:
                city_name = city.get('name', 'Unknown')
                city_id = city.get('id', 'N/A')
                print(f"       • {city_name} (ID: {city_id})")

        print()


def cmd_conditions_weather(manager, args):
    """Query weather conditions supported by automation"""
    conditions = manager.get_weather_conditions()


    if not conditions:
        print("\n❌ No weather conditions found")
        return

    print(f"\n🌤️ Found {len(conditions)} weather condition(s):\n")
    print("=" * 60)

    import json
    # Convert conditions to json
    print(json.dumps(conditions, ensure_ascii=False, indent=2))


def cmd_device_func(manager, args):
    """Get device function set"""
    device_id = args.device_id

    print(f"\n🔄 Getting device function set for {device_id}...")
    result = manager.get_device_functions(device_id)

    if not result:
        print("❌ Get failed")
        return

    category = result.get('category', 'N/A')
    functions = result.get('functions', [])

    print(f"\n📋 Device Function Set:\n")
    print("=" * 60)
    print(f"Category code: {category}")
    print(f"Function count: {len(functions)}\n")


# code	String	Instruction
# type	String	Instruction type
# values	String	Instruction parameter range
# name	String	Instruction name
# desc	String	Description


    for idx, func in enumerate(functions, 1):
        name = func.get('name', '')
        desc = func.get('desc', '')
        code = func.get('code', '')
        type_val = func.get('type', '')
        values = func.get('values', '')

        # Print serial number
        print(f"{idx}. dp name: {name}")
        # print(f"     description desc: {desc}")
        print(f"   dpCode: {code}")
        print(f"   dpValueType: {type_val}")
        print(f"   dpValue range: {values}")
        print()


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description='🏠 Tuya Smart Device Control Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  %(prog)s list                          # List all devices
  %(prog)s family_list                   # List family list
  %(prog)s family_devices <home_id>      # List devices for specified family
  %(prog)s family_rooms <home_id>        # List rooms for specified family
  %(prog)s scene_list <home_id>          # List scenes for specified family
  %(prog)s automations <home_id>         # List automations for specified family
  %(prog)s automation_on <home_id> <automation_id>      # Enable automation
  %(prog)s automation_off <home_id> <automation_id>     # Disable automation
  %(prog)s automation_del <home_id> <automation_id>     # Delete automation
  %(prog)s add_automation <home_id>      # Add automation (requires --json or --json-file)
  %(prog)s devices                       # List user's device list
  %(prog)s cities                        # Query city list
  %(prog)s conditions_weather            # Query weather conditions supported by automation
  %(prog)s device_func <device_id>       # Get device function set
  %(prog)s on <device_id>                # Turn on device
  %(prog)s off <device_id>               # Turn off device
  %(prog)s status <device_id>            # Query device status
  %(prog)s find "living room"            # Search device
  %(prog)s brightness <device_id> 80     # Set brightness to 80%%
  %(prog)s batch-on id1 id2 id3          # Batch turn on multiple devices

Environment variables:
  Can be configured in two ways:

  Method 1 (Recommended): Create config.env file in project root directory
    TUYA_ACCESS_ID     - Tuya Access ID (required)
    TUYA_ACCESS_SECRET - Tuya Access Secret (required)
    TUYA_UID           - Tuya User UID (recommended)
    TUYA_ENDPOINT      - API endpoint (optional, defaults to China region)
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # list command
    parser_list = subparsers.add_parser('list', help='List all devices')
    parser_list.set_defaults(func=cmd_list)

    # family_list command
    parser_family_list = subparsers.add_parser('family_list', help='List family list')
    parser_family_list.set_defaults(func=cmd_family_list)

    # scene_list command
    parser_scene_list = subparsers.add_parser('scene_list', help='List scene list')
    parser_scene_list.add_argument('home_id', help='Family ID')
    parser_scene_list.set_defaults(func=cmd_scene_list)

    # devices command
    parser_devices = subparsers.add_parser('devices', help="List user's device list")
    parser_devices.set_defaults(func=cmd_devices)

    # family_devices command
    parser_family_devices = subparsers.add_parser('family_devices', help='List devices for specified family')
    parser_family_devices.add_argument('home_id', help='Family ID')
    parser_family_devices.set_defaults(func=cmd_family_devices)

    # family_rooms command
    parser_family_rooms = subparsers.add_parser('family_rooms', help='List rooms for specified family')
    parser_family_rooms.add_argument('home_id', help='Family ID')
    parser_family_rooms.set_defaults(func=cmd_family_rooms)

    # automations command
    parser_automations = subparsers.add_parser('automations', help='List automation list')
    parser_automations.add_argument('home_id', help='Family ID')
    parser_automations.set_defaults(func=cmd_automations)

    # add_automation command
    parser_add_automation = subparsers.add_parser('add_automation', help='Add automation')
    parser_add_automation.add_argument('home_id', help='Family ID')
    parser_add_automation.add_argument('--json', '-j', help='Automation configuration JSON string')
    parser_add_automation.add_argument('--json-file', '-f', help='Automation configuration JSON file path')
    parser_add_automation.set_defaults(func=cmd_add_automation)

    # automation_on command
    parser_automation_on = subparsers.add_parser('automation_on', help='Enable automation')
    parser_automation_on.add_argument('home_id', help='Family ID')
    parser_automation_on.add_argument('automation_id', help='Automation ID')
    parser_automation_on.set_defaults(func=cmd_automation_on)

    # automation_off command
    parser_automation_off = subparsers.add_parser('automation_off', help='Disable automation')
    parser_automation_off.add_argument('home_id', help='Family ID')
    parser_automation_off.add_argument('automation_id', help='Automation ID')
    parser_automation_off.set_defaults(func=cmd_automation_off)

    # automation_del command
    parser_automation_del = subparsers.add_parser('automation_del', help='Delete automation')
    parser_automation_del.add_argument('home_id', help='Family ID')
    parser_automation_del.add_argument('automation_id', help='Automation ID')
    parser_automation_del.set_defaults(func=cmd_automation_del)

    # cmd_control command
    parser_control = subparsers.add_parser('control', help='Control device (on/off/set)')
    parser_control.add_argument('device_id', help='Device ID')
    parser_control.add_argument('dp_code', help='DP code (e.g., switch_1, bright_value)')
    parser_control.add_argument('dp_value', help='DP value')
    parser_control.set_defaults(func=cmd_control)

    # on command
    parser_on = subparsers.add_parser('on', help='Turn on device')
    parser_on.add_argument('device_id', help='Device ID')
    parser_on.add_argument('--switch', '-s', help='Switch DP code (default: switch_1)')
    parser_on.set_defaults(func=cmd_on)

    # off command
    parser_off = subparsers.add_parser('off', help='Turn off device')
    parser_off.add_argument('device_id', help='Device ID')
    parser_off.add_argument('--switch', '-s', help='Switch DP code (default: switch_1)')
    parser_off.set_defaults(func=cmd_off)

    # status command
    parser_status = subparsers.add_parser('status', help='Query device status')
    parser_status.add_argument('device_id', help='Device ID')
    parser_status.set_defaults(func=cmd_status)

    # find command
    parser_find = subparsers.add_parser('find', help='Find device by name')
    parser_find.add_argument('name', help='Device name keyword')
    parser_find.set_defaults(func=cmd_find)

    # set command
    parser_set = subparsers.add_parser('set', help='Set device DP value')
    parser_set.add_argument('device_id', help='Device ID')
    parser_set.add_argument('dp_code', help='DP code (e.g., switch_1, bright_value)')
    parser_set.add_argument('dp_value', help='DP value')
    parser_set.set_defaults(func=cmd_set)

    # brightness command
    parser_bright = subparsers.add_parser('brightness', help='Set device brightness')
    parser_bright.add_argument('device_id', help='Device ID')
    parser_bright.add_argument('value', type=int, help='Brightness value (1-100)')
    parser_bright.set_defaults(func=cmd_brightness)

    # temperature command
    parser_temp = subparsers.add_parser('temperature', help='Set device temperature')
    parser_temp.add_argument('device_id', help='Device ID')
    parser_temp.add_argument('value', type=int, help='Temperature value')
    parser_temp.set_defaults(func=cmd_temp)

    # batch-on command
    parser_batch_on = subparsers.add_parser('batch-on', help='Batch turn on devices')
    parser_batch_on.add_argument('device_ids', nargs='+', help='Device ID list')
    parser_batch_on.set_defaults(func=cmd_batch_on)

    # batch-off command
    parser_batch_off = subparsers.add_parser('batch-off', help='Batch turn off devices')
    parser_batch_off.add_argument('device_ids', nargs='+', help='Device ID list')
    parser_batch_off.set_defaults(func=cmd_batch_off)

    # info command
    parser_info = subparsers.add_parser('info', help='Get device detailed information')
    parser_info.add_argument('device_id', help='Device ID')
    parser_info.set_defaults(func=cmd_info)

    # cities command
    parser_cities = subparsers.add_parser('cities', help='Query city list')
    parser_cities.set_defaults(func=cmd_cities)

    # conditions_weather command
    parser_conditions_weather = subparsers.add_parser('conditions_weather', help='Query weather conditions supported by automation')
    parser_conditions_weather.set_defaults(func=cmd_conditions_weather)

    # device_func command
    parser_device_func = subparsers.add_parser('device_func', help='Get device function set')
    parser_device_func.add_argument('device_id', help='Device ID')
    parser_device_func.set_defaults(func=cmd_device_func)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize device manager
    try:
        print("\n🏠 Tuya Smart Device Control")
        print("=" * 40)
        manager = TuyaDeviceManager()
    except ValueError as e:
        print(f"\n❌ {e}")
        print("\nCreate config.env file in project root directory with the following content:")
        print("  ```")
        print("  TUYA_ACCESS_ID=your-access-id")
        print("  TUYA_ACCESS_SECRET=your-access-secret")
        print("  TUYA_UID=your-uid")
        print("  TUYA_ENDPOINT=https://openapi.xxx.com")
        print("  ```")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Initialization failed: {str(e)}")
        sys.exit(1)

    # Execute command
    try:
        args.func(manager, args)
    except Exception as e:
        print(f"\n❌ Command execution failed: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
