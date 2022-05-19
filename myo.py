import asyncio, yaml, struct
from enum import Enum
from bleak import BleakClient

class ClassifierEventType(Enum):
    ARM_SYNCED = 0x01
    ARM_UNSYNCED = 0x02
    POSE = 0x03
    UNLOCKED = 0x04
    LOCKED = 0x05
    SYNC_FAILED = 0x06

class Arm(Enum):
    RIGHT = 0x01
    LEFT = 0x02
    UNKNOWN = 0xff

class Pose(Enum):
    REST = 0x00
    FIST = 0x01
    WAVE_IN = 0x02
    WAVE_OUT = 0x03
    FINGERS_SPREAD = 0x04
    DOUBLE_TAP = 0x05
    UNKNOWN = 0xff  

class XDirection(Enum):
    TOWARD_WRIST = 0x01
    TOWARD_ELBOW = 0x02
    UNKNOWN = 0xff      




def handle_battery_notification(data):
    characteristic = 'Battery Level'
    print(f"{characteristic}: {int.from_bytes(data, 'little')}")

def handle_classifier_indication(data):
    characteristic = 'Classifier Event'
    print(f"len(data): {len(data)}")
    event_id, value_id, x_direction_id, _, _, _ = struct.unpack('<6B', data) #TODO what are the 3 bytes at the end?
    event = ClassifierEventType(event_id)
    classifier_value = None
    x_direction = None
    match event:
        case ClassifierEventType.ARM_SYNCED:
            classifier_value = Arm(value_id)      
            x_direction = XDirection(x_direction_id)            
        case ClassifierEventType.ARM_UNSYNCED:
            classifier_value = Arm(value_id)    
            x_direction = XDirection(x_direction_id)         
        case ClassifierEventType.POSE:
            classifier_value = Pose(value_id)                                                                                       
        case ClassifierEventType.UNLOCKED:
            pass
        case ClassifierEventType.LOCKED:
            pass
        case ClassifierEventType.SYNC_FAILED:
            pass
        case _:
            event = "Unknown Event"
    print_value = f"Classifier Event: {event} "
    print_value += f"classifier_value: {classifier_value} " if classifier_value else ""
    print_value += f"x_direction: {x_direction}" if x_direction else ""
    print_value += f" data: {data}"
    print(print_value) 

def ble_notification_callback(handle, data):
    match handle:
        case 16:
            handle_battery_notification(data)
        case 34:
            handle_classifier_indication(data)
        case _:
            characteristic = 'Unknown Characteristic'
            print(f"{characteristic}: Handle: {handle} Data: {data}")


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

    ble_device_uuid = device_config["device"][0]['device_uuid']
    # ble_device_uuid = 'EDC1E6C0-B2AB-362E-9A2B-AC0913FF36DF'
    print(f"Connecting to {ble_device_uuid}")

    async with BleakClient(ble_device_uuid) as client:
        # await list_ble_characteristics(client)

        rssi = await client.get_rssi()
        print(f"Connected.")
        print(f"Signal Strength: {rssi} dBm")


        # Get Device Manufacturer #################################################################
        device_manufacturer_characteristic = '0000{0:x}-0000-1000-8000-00805f9b34fb'.format(0x2a29)
        device_manufacturer_char = await client.read_gatt_char(device_manufacturer_characteristic)
        device_manufacturer = device_manufacturer_char.decode('utf-8')
        print(f"Manufacturer: {device_manufacturer}")
        ##########################################################################################


        # # Unknown Notify Characteristic ##########################################################
        # unknown_notify_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0104)
        # await client.start_notify(unknown_notify_characteristic, ble_notification_callback) 
        # ##########################################################################################



        command_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0401)  # 0x19
        # typedef enum {
        #     myohw_command_set_mode               = 0x01, ///< Set EMG and IMU modes. See myohw_command_set_mode_t.
        #     myohw_command_vibrate                = 0x03, ///< Vibrate. See myohw_command_vibrate_t.
        #     myohw_command_deep_sleep             = 0x04, ///< Put Myo into deep sleep. See myohw_command_deep_sleep_t.
        #     myohw_command_vibrate2               = 0x07, ///< Extended vibrate. See myohw_command_vibrate2_t.
        #     myohw_command_set_sleep_mode         = 0x09, ///< Set sleep mode. See myohw_command_set_sleep_mode_t.
        #     myohw_command_unlock                 = 0x0a, ///< Unlock Myo. See myohw_command_unlock_t.
        #     myohw_command_user_action            = 0x0b, ///< Notify user that an action has been recognized / confirmed.
        #                                                  ///< See myohw_command_user_action_t.

        # # # User action notification ################################################################
        # # # typedef struct MYOHW_PACKED {
        # # #     myohw_command_header_t header; ///< command == myohw_command_user_action. payload_size == 1.
        # # #     uint8_t type;                  ///< Type of user action that occurred. See myohw_user_action_type_t.
        # # # } myohw_command_user_action_t;
        # # # MYOHW_STATIC_ASSERT_SIZED(myohw_command_user_action_t, 3);     
        # # # 
        # # # /// User action types.
        # # # typedef enum {
        # # #     myohw_user_action_single = 0, ///< User did a single, discrete action, such as pausing a video.
        # # # } myohw_user_action_type_t;   
        # command = 0x0b # set sleep mode
        # action_type = 0 # TODO is this correct? Does a separate notify characteristic need to be enabled?
        # payload_byte_size = 2
        # command_header = struct.pack('<3B', command, payload_byte_size, action_type)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)
        # # ###########################################################################################


        # Command to set EMG and IMU modes
        command =  0x01
        # myo samples at a constant rate of 200 Hz.
        # myohw_emg_mode_none         = 0x00, # Do not send EMG data.
        #                               0x01  # Undocumented filtered 50Hz.
        # myohw_emg_mode_send_emg     = 0x02, # Send filtered EMG data.
        # myohw_emg_mode_send_emg_raw = 0x03, # Send raw (unfiltered) EMG data.        
        emg_mode = 0x00
        # myohw_imu_mode_none        = 0x00, # Do not send IMU data or events.
        # myohw_imu_mode_send_data   = 0x01, # Send IMU data streams (accelerometer, gyroscope, and orientation).
        # myohw_imu_mode_send_events = 0x02, # Send motion events detected by the IMU (e.g. taps).
        # myohw_imu_mode_send_all    = 0x03, # Send both IMU data streams and motion events.
        # myohw_imu_mode_send_raw    = 0x04, # Send raw IMU data streams.        
        imu_mode = 0x00
        # myohw_classifier_mode_disabled = 0x00, # Disable and reset the internal state of the onboard classifier.
        # myohw_classifier_mode_enabled  = 0x01, # Send classifier events (poses and arm events).
        classifier_mode = 0x01
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, emg_mode, imu_mode, classifier_mode) #  b'\x01\x02\x00\x00'
        await client.write_gatt_char(command_characteristic, command_header, response=True)  
        await client.start_notify('d5060103-a904-deb9-4748-2c7f4a124842', ble_notification_callback) # subscribe to battery level notifications


        # Get Device Info #################################################################
        device_info_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0101)
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
        battery_level_characteristic = '0000{0:x}-0000-1000-8000-00805f9b34fb'.format(0x2a19)
        battery_level_char = await client.read_gatt_char(battery_level_characteristic)
        battery_level = int.from_bytes(battery_level_char, 'big')
        print(f"Battery Level: {battery_level}") # Get initial battery level
        await client.start_notify(battery_level_characteristic, ble_notification_callback) # subscribe to battery level notifications
        #########################################################################################

        # Get Revision Info #####################################################################
        revision_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0201)
        firmware_revision_value = await client.read_gatt_char(revision_characteristic)
        major = int.from_bytes(firmware_revision_value[0:2], 'little') # Major
        minor = int.from_bytes(firmware_revision_value[2:4], 'little') # Minor
        patch = int.from_bytes(firmware_revision_value[4:6], 'little') # Patch
        hardware_revision = int.from_bytes(firmware_revision_value[6:8], 'little') # Hardware Revision
        print(f"Myo Firmware Version: {major}.{minor}.{patch}.{hardware_revision}")                        
        #########################################################################################

        # Set LED mode ######################################################################
        command = 0x06 # set led mode
        # 128 128 255 is a very nice purple
        payload = [128, 128, 255, 128, 128, 255] # first 3 bytes is the logo color, second 3 bytes is the bar color
        payload_byte_size = len(payload)
        command_header = struct.pack('<8B', command, payload_byte_size, *payload) 
        await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################

        # Sleep mode ######################################################################
        command = 0x09 # set sleep mode
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
        command = 0x03 # set vibrate mode
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
        # command = 0x07 # set vibrate2 mode
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

        # Unlock command ######################################################################
        command = 0x0a # unlock myo
        lock_mode = 0x02 # myohw_unlock_hold
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, lock_mode)
        await client.write_gatt_char(command_characteristic, command_header, response=True)      
        ###########################################################################################


        # Deep sleep command ######################################################################
        # WARNING: This will immediately disconnect and put the Myo into a deep sleep that can only 
        # be awakened by plugging it into USB
        # command = 0x04 # set deep sleep mode
        # payload_byte_size = 1
        # command_header = struct.pack('<2B', command, payload_byte_size)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################


        await asyncio.sleep(120)  




if __name__ == '__main__':
    asyncio.run(main())
