import asyncio, yaml, struct
from bleak import BleakClient, BleakScanner

# def convert_UUID_to_hex(the_value):
#     the_value = the_value.replace('-', '')
#     the_value = the_value[::-1] #reverse the string
#     hexArrayStr = ''
#     splitToTwos = map(''.join, zip(*[iter(the_value)]*2))
#     count = 0
#     for v in splitToTwos:
#         count+=1
#         hexArrayStr = hexArrayStr + ('\x'+(v[::-1]).lower())
#     return hexArrayStr

def ble_notification_callback(handle, data):
    match handle:
        case 16:
            characteristic = 'Battery Level'
        case _:
            characteristic = 'Unknown Characteristicc'
    print(f"{characteristic}: {int.from_bytes(data, 'little')}")


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
        command_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0401)  # 0x19
        rssi = await client.get_rssi()
        print(f"Connected.")
        print(f"Signal Strength: {rssi} dBm")


        # Get Device Manufacturer #################################################################
        device_manufacturer_characteristic = '0000{0:x}-0000-1000-8000-00805f9b34fb'.format(0x2a29)
        device_manufacturer_char = await client.read_gatt_char(device_manufacturer_characteristic)
        device_manufacturer = device_manufacturer_char.decode('utf-8')
        print(f"Manufacturer: {device_manufacturer}")
        ##########################################################################################


        # Unknown Characteristic #################################################################
        # unknown_notify_characteristic = "d5060{0:x}-a904-deb9-4748-2c7f4a124842".format(0x0104)
        # await client.start_notify(unknown_notify_characteristic, ble_notification_callback) 
        # unknown_char = await client.read_gatt_char(unknown_notify_characteristic)
        # print(unknown_char)
        ##########################################################################################


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
        classifier_mode = 0x00
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, emg_mode, imu_mode, classifier_mode) #  b'\x01\x02\x00\x00'
        await client.write_gatt_char(command_characteristic, command_header, response=True)  


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
        # battery_level_char = await client.read_gatt_char(battery_level_characteristic)
        # battery_level = int.from_bytes(battery_level_char, 'big')
        # print(battery_level)
        await client.start_notify(battery_level_characteristic, ble_notification_callback) 
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

        # typedef enum {
        #     myohw_command_set_mode               = 0x01, ///< Set EMG and IMU modes. See myohw_command_set_mode_t.
        #     myohw_command_vibrate                = 0x03, ///< Vibrate. See myohw_command_vibrate_t.
        #     myohw_command_deep_sleep             = 0x04, ///< Put Myo into deep sleep. See myohw_command_deep_sleep_t.
        #     myohw_command_vibrate2               = 0x07, ///< Extended vibrate. See myohw_command_vibrate2_t.
        #     myohw_command_set_sleep_mode         = 0x09, ///< Set sleep mode. See myohw_command_set_sleep_mode_t.
        #     myohw_command_unlock                 = 0x0a, ///< Unlock Myo. See myohw_command_unlock_t.
        #     myohw_command_user_action            = 0x0b, ///< Notify user that an action has been recognized / confirmed.
        #                                                  ///< See myohw_command_user_action_t.

        # Set LED mode ######################################################################
        command = 0x06 # set led mode
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


        # Vibration mode ######################################################################
        # typedef enum {
        #     myohw_vibration_none   = 0x00, ///< Do not vibrate.
        #     myohw_vibration_short  = 0x01, ///< Vibrate for a short amount of time.
        #     myohw_vibration_medium = 0x02, ///< Vibrate for a medium amount of time.
        #     myohw_vibration_long   = 0x03, ///< Vibrate for a long amount of time.
        # } myohw_vibration_type_t;
        command = 0x03 # set vibrate mode
        vibrate_mode = 0x00 # myohw_vibration_none
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, vibrate_mode)
        await client.write_gatt_char(command_characteristic, command_header, response=True)      
        ###########################################################################################


        # Unlock command ######################################################################
        command = 0x0a # unlock myo
        lock_mode = 0x02 # myohw_unlock_hold
        payload_byte_size = 1
        command_header = struct.pack('<3B', command, payload_byte_size, lock_mode)
        # await client.start_notify(command_characteristic, ble_notification_callback)
        await client.write_gatt_char(command_characteristic, command_header, response=True)      
        ###########################################################################################


        # Deep sleep command ######################################################################
        # typedef struct MYOHW_PACKED {
        #     myohw_command_header_t header; ///< command == myohw_command_deep_sleep. payload_size == 0.
        # } myohw_command_deep_sleep_t;
        # MYOHW_STATIC_ASSERT_SIZED(myohw_command_deep_sleep_t, 2);
        # command = 0x04 # set deep sleep mode # immediately disconnects and puts to sleep
        # payload_byte_size = 1
        # command_header = struct.pack('<2B', command, payload_byte_size)
        # await client.write_gatt_char(command_characteristic, command_header, response=True)
        ###########################################################################################


        await asyncio.sleep(120)  




if __name__ == '__main__':
    asyncio.run(main())
