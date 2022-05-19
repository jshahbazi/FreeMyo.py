import asyncio, binascii,yaml, struct
from tkinter import RIGHT
from enum import Enum
from bleak import BleakClient

CLASSIFIER_EVENT_TYPES = {
    1: 'ARM_SYNCED',
    2: 'ARM_UNSYNCED',
    3: 'POSE',
    4: 'UNLOCKED',
    5: 'LOCKED',
    6: 'SYNC_FAILED',
}

ARM_VALUES = {
    0: 'UNKNOWN',
    1: 'RIGHT',
    2: 'LEFT',
    255: 'UNKNOWN',
}

POSE_VALUES = {
    0: 'REST',
    1: 'FIST',
    2: 'WAVE_IN',
    3: 'WAVE_OUT',
    4: 'FINGERS_SPREAD',
    5: 'DOUBLE_TAP',
    255: 'UNKNOWN'
}

XDIRECTION_VALUES = {
    1: 'TOWARD_WRIST',
    2: 'TOWARD_ELBOW',
    255: 'UNKNOWN'
}





# Myo samples at a constant rate of 200 HZ
EMG_MODE = {
    'OFF': 0,           # Do not send EMG data
    'FILTERED_50HZ': 1, # Undocumented filtered 50Hz
    'FILTERED': 2,      # Send filtered EMG data
    'RAW': 3,           # Send raw (unfiltered) EMG data
}

IMU_MODE = {
    'OFF': 0,           # Do not send IMU data or events
    'SEND_DATA': 1,     # Send IMU data streams (accelerometer, gyroscope, and orientation)
    'SEND_EVENTS': 2,   # Send motion events detected by the IMU (e.g. taps)
    'SEND_ALL': 3,      # Send both IMU data streams and motion events
    'SEND_RAW': 4,      # Send raw IMU data streams 
}

CLASSIFIER_MODE = {
    'DISABLED': 0,     # Disable and reset the internal state of the onboard classifier
    'ENABLED': 1,      # Send classifier events (poses and arm events)
}

COMMAND = {
    'SET_EMG_IMU_MODE': 1,    # Set EMG and IMU and Classifier modes
    'VIBRATE': 3,             # Vibrate
    'DEEP_SLEEP': 4,          # Put Myo into deep sleep
    'LED': 6,                 # Set LED mode
    'EXTENDED_VIBRATION': 7,  # Extended vibrate
    'SET_SLEEP_MODE': 9,      # Set sleep mode
    'UNLOCK': 10,             # Unlock Myo
    'USER_ACTION': 11,        # Notify user that an action has been recognized / confirmed
}    


def handle_battery_notification(data):
    characteristic = 'Battery Level'
    print(f"{characteristic}: {int.from_bytes(data, 'little')}")

def handle_classifier_indication(data):
    event_id, value_id, x_direction_id, _, _, _ = struct.unpack('<6B', data) #TODO what are the 3 bytes at the end?
    classifier_event = CLASSIFIER_EVENT_TYPES[event_id]
    classifier_value = None
    x_direction = None
    match classifier_event:
        case 'ARM_SYNCED':
            classifier_value = ARM_VALUES[value_id]
            x_direction = XDIRECTION_VALUES[x_direction_id]
        case 'ARM_UNSYNCED':
            pass
        case 'POSE':
            classifier_value = POSE_VALUES[value_id]
        case 'UNLOCKED':
            pass
        case 'LOCKED':
            pass
        case 'SYNC_FAILED':
            pass
        case _:
            classifier_event = "Unknown Event"
    print_value = f"{classifier_event} >>> "
    print_value += f"{classifier_value} " if classifier_value else ""
    print_value += f"x_direction: {x_direction}" if x_direction else ""
    print(print_value) 

def ble_notification_callback(handle, data):
    match handle:
        case 16:
            handle_battery_notification(data)
        case 34:
            handle_classifier_indication(data)
        case _:
            print(f"Unknown Characteristic: Handle: {handle} Data: {data}")


async def list_ble_characteristics(client):
    for service in client.services:
        print("[Service] {0}: {1}".format(service.uuid, service.description))
        for characteristic in service.characteristics:
            if "read" in characteristic.properties:
                try:
                    value = bytes(await client.read_gatt_char(characteristic.uuid))
                except Exception as e:
                    value = str(e).encode()
            else:
                value = None
            print(
                "\t[Characteristic] {0}: ({1}) | Name: {2}, Value: {3} ".format(
                    characteristic.uuid, ",".join(characteristic.properties), characteristic.description, value
                )
            )
            for descriptor in characteristic.descriptors:
                value = await client.read_gatt_descriptor(descriptor.handle)
                print("\t\t[Descriptor] {0}: (Handle: {1}) | Value: {2} ".format(descriptor.uuid, descriptor.handle, bytes(value)))
    

async def main():
    with open("myo_config.yaml", "r") as stream:
        try:
            device_config = yaml.safe_load(stream)
            # print(device_config)
        except Exception as e:
            print(f"Error reading config file: {e}")
            return

    ble_device_uuid = device_config['myo_armband']['device_uuid']
    # ble_device_uuid = 'EDC1E6C0-B2AB-362E-9A2B-AC0913FF36DF'
    print(f"Connecting to {ble_device_uuid}")

    async with BleakClient(ble_device_uuid) as client:
        # await list_ble_characteristics(client)

        rssi = await client.get_rssi()
        print(f"Connected.")
        print(f"Signal Strength: {rssi} dBm")


        # Get Device Manufacturer #################################################################
        device_manufacturer_characteristic = device_config['myo_armband']['characteristics']['manufacturer']
        device_manufacturer_char = await client.read_gatt_char(device_manufacturer_characteristic)
        device_manufacturer = device_manufacturer_char.decode('utf-8')
        print(f"Manufacturer: {device_manufacturer}")
        ##########################################################################################


        # # Unknown Notify Characteristic ##########################################################
        # unknown_notify_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0104)
        # await client.start_notify(unknown_notify_characteristic, ble_notification_callback) 
        # ##########################################################################################



        command_characteristic = device_config['myo_armband']['characteristics']['command']


        # Unlock command ######################################################################
        command = 0x0a # unlock myo
        lock_mode = 0x02 # myohw_unlock_hold
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, lock_mode)
        await client.write_gatt_char(command_characteristic, command_header, response=True)      
        ###########################################################################################
    

        # Command to set EMG and IMU modes
        command =  COMMAND['SET_EMG_IMU_MODE']     
        emg_mode = EMG_MODE['OFF']     
        imu_mode = IMU_MODE['OFF']
        classifier_mode = CLASSIFIER_MODE['ENABLED']
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, emg_mode, imu_mode, classifier_mode) #  b'\x01\x02\x00\x00'
        await client.write_gatt_char(command_characteristic, command_header, response=True)  
        ###########################################################################################


        # Subscribe to Classifier Notifications ###################################################
        # This is actually an indicate property, but Bleak abstracts out the required response and treats it like a notification
        classifier_event_characteristic = device_config['myo_armband']['characteristics']['classifier_event']
        await client.start_notify(classifier_event_characteristic, ble_notification_callback)
        ###########################################################################################


        # # # User action notification ################################################################
        # # # typedef enum {
        # # #     myohw_user_action_single = 0, ///< User did a single, discrete action, such as pausing a video.
        # # # } myohw_user_action_type_t;   
        # command = 0x0b
        # action_type = 0 # TODO is this correct? Does a separate notify characteristic need to be enabled?
        # payload_byte_size = 2
        # command_header = struct.pack('<3B', command, payload_byte_size, action_type)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)
        # # ###########################################################################################


        # Get Device Info #################################################################
        device_info_characteristic = device_config['myo_armband']['characteristics']['device_info']
        device_info_char = await client.read_gatt_char(device_info_characteristic)
        info = struct.unpack("<6BHBBBBB7B", device_info_char) #20
        serial_number = '-'.join(map(str,info[0:6]))
        unlock_pose = int.from_bytes(device_info_char[6:8], 'little')
        active_classifier_type_num = device_info_char[8]
        match active_classifier_type_num:
            case 0:
                active_classifier_type = "Built in"
            case 1:
                active_classifier_type = "Personalized"
            case _:
                active_classifier_type = "Unknown"                                
        active_classifier_index = device_info_char[9]
        has_custom_classifier = True if device_info_char[10] else False
        stream_indicating = True if device_info_char[11] else False
        sku = device_info_char[12]
        match sku:
            case 0:
                sku_type = "Unknown (old)"
            case 1:
                sku_type = "Black Myo"
            case 2:
                sku_type = "White Myo"          
        reserved = info[13:21] # unused
        print(f"Serial Number: {serial_number}")
        print(f"Unlock Pose: {unlock_pose}")
        print(f"Active Classifier Type: {active_classifier_type}")
        print(f"Active Classifier Index: {active_classifier_index}")
        print(f"Has Custom Classifier: {has_custom_classifier}")
        print(f"Stream Indicating: {stream_indicating}")
        print(f"SKU: {sku_type}")
        #########################################################################################
     

        # Get Battery Info ######################################################################
        battery_level_characteristic = device_config['myo_armband']['characteristics']['battery_level']
        battery_level_char = await client.read_gatt_char(battery_level_characteristic)
        battery_level = int.from_bytes(battery_level_char, 'big')
        print(f"Battery Level: {battery_level}") # Get initial battery level
        await client.start_notify(battery_level_characteristic, ble_notification_callback) # subscribe to battery level notifications
        #########################################################################################


        # Get Revision Info #####################################################################
        revision_characteristic = device_config['myo_armband']['characteristics']['revision']
        firmware_revision_value = await client.read_gatt_char(revision_characteristic)
        major = int.from_bytes(firmware_revision_value[0:2], 'little') # Major
        minor = int.from_bytes(firmware_revision_value[2:4], 'little') # Minor
        patch = int.from_bytes(firmware_revision_value[4:6], 'little') # Patch
        hardware_revision = int.from_bytes(firmware_revision_value[6:8], 'little') # Hardware Revision
        print(f"Myo Firmware Version: {major}.{minor}.{patch}.{hardware_revision}")                        
        #########################################################################################


        # Set LED mode ######################################################################
        command = COMMAND['LED'] 
        # 128 128 255 is a very nice purple
        payload = [128, 128, 255, 128, 128, 255] # first 3 bytes is the logo color, second 3 bytes is the bar color
        payload_byte_size = len(payload)
        command_header = struct.pack('<8B', command, payload_byte_size, *payload) 
        await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################


        # Sleep mode ######################################################################
        command = COMMAND['SET_SLEEP_MODE'] 
        sleep_mode = 0x01 # 1 is myohw_sleep_mode_never_sleep, 0 is myohw_sleep_mode_normal
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, sleep_mode)
        await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################


        # Vibration command ######################################################################
        # Use this to send a vibration whenever you want
        # typedef enum {
        #     myohw_vibration_none   = 0x00, ///< Do not vibrate.
        #     myohw_vibration_short  = 0x01, ///< Vibrate for a short amount of time.
        #     myohw_vibration_medium = 0x02, ///< Vibrate for a medium amount of time.
        #     myohw_vibration_long   = 0x03, ///< Vibrate for a long amount of time.
        # } myohw_vibration_type_t;
        command = COMMAND['VIBRATE'] 
        vibration_type = 0x00 # myohw_vibration_none
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, vibration_type)
        await client.write_gatt_char(command_characteristic, command_header, response=True)      
        ###########################################################################################


        # # Extended Vibration mode ######################################################################
        # Use this to send more complex vibrations
        # # typedef struct MYOHW_PACKED {
        # #     myohw_command_header_t header; ///< command == myohw_command_vibrate2. payload_size == 18.
        # #     struct MYOHW_PACKED {
        # #         uint16_t duration;         ///< duration (in ms) of the vibration
        # #         uint8_t strength;          ///< strength of vibration (0 - motor off, 255 - full speed)
        # #     } steps[MYOHW_COMMAND_VIBRATE2_STEPS];
        # # } myohw_command_vibrate2_t;
        # # MYOHW_STATIC_ASSERT_SIZED(myohw_command_vibrate2_t, 20);
        # command = COMMAND['EXTENDED_VIBRATION'] 
        # steps = b''
        # number_of_steps = 6 # set the number of times to vibrate        
        # for _ in range(number_of_steps):
        #     duration = 1000 # duration (in ms) of the vibration step
        #     strength = 255 # strength of vibration step (0 - motor off, 255 - full speed)            
        #     steps += struct.pack('<HB', duration, strength)
        # payload_byte_size = len(steps)
        # command_header = struct.pack('<' + 'BB' + payload_byte_size * 'B', command, payload_byte_size, *steps)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)      
        # ###########################################################################################



        # Deep sleep command ######################################################################
        # WARNING: This will immediately disconnect and put the Myo into a deep sleep that can only 
        # be awakened by plugging it into USB
        # command = COMMAND['DEEP_SLEEP'] 
        # payload_byte_size = 1
        # command_header = struct.pack('<2B', command, payload_byte_size)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################


        # print(await client.read_gatt_descriptor(18)) #0x00
        # print(await client.read_gatt_descriptor(29))
        # print(await client.read_gatt_descriptor(32))
        # print(await client.read_gatt_descriptor(36)) #0x00, 0x00
        # print(await client.read_gatt_descriptor(40))
        # print(await client.read_gatt_descriptor(44))
        # print(await client.read_gatt_descriptor(47))
        # print(await client.read_gatt_descriptor(50))
        # print(await client.read_gatt_descriptor(53))
        # print(await client.read_gatt_descriptor(57))

        await asyncio.sleep(120)  




if __name__ == '__main__':
    asyncio.run(main())
