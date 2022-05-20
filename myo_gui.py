import asyncio, time, struct, yaml
import dearpygui.dearpygui as dpg
from bleak import BleakClient, BleakError


CLASSIFIER_EVENT_TYPES = {
    1: 'ARM_SYNCED',
    2: 'ARM_UNSYNCED',
    3: 'POSE',
    4: 'UNLOCKED',
    5: 'LOCKED',
    6: 'SYNC_FAILED',
    7: 'UNKNOWN', # I've only seen this once
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




COMMAND = {
    'SET_EMG_IMU_MODE':   1, # Set EMG and IMU and Classifier modes
    'VIBRATE':            3, # Vibrate
    'DEEP_SLEEP':         4, # Put Myo into deep sleep
    'LED':                6, # Set LED mode
    'EXTENDED_VIBRATION': 7, # Extended vibrate
    'SET_SLEEP_MODE':     9, # Set sleep mode
    'UNLOCK':            10, # Unlock Myo
    'USER_ACTION':       11, # Notify user that an action has been recognized / confirmed
}  

# Myo samples at a constant rate of 200 HZ
EMG_MODE = {
    'OFF':           0, # Do not send EMG data
    'FILTERED_50HZ': 1, # Undocumented filtered 50Hz
    'FILTERED':      2, # Send filtered EMG data
    'RAW':           3, # Send raw (unfiltered) EMG data
}

IMU_MODE = {
    'OFF':           0, # Do not send IMU data or events
    'SEND_DATA':     1, # Send IMU data streams (accelerometer, gyroscope, and orientation)
    'SEND_EVENTS':   2, # Send motion events detected by the IMU (e.g. taps)
    'SEND_ALL':      3, # Send both IMU data streams and motion events
    'SEND_RAW':      4, # Send raw IMU data streams 
}

VIBRATION_DURATION = {
    'NONE':         0, # Do not vibrate
    'SHORT':        1, # Vibrate for a short amount of time
    'MEDIUM':       2, # Vibrate for a medium amount of time
    'LONG':         3, # Vibrate for a long amount of time
}

SLEEP_MODE = {
    'NORMAL':        0, # Normal sleep mode; Myo will sleep after a period of inactivity
    'NEVER_SLEEP':   1, # Never go to sleep
}

UNLOCK_COMMAND = {
    'UNLOCK_RELOCK': 0, # Unlock then re-lock immediately
    'UNLOCK_TIMED':  1, # Unlock now and re-lock after a fixed timeout
    'UNLOCK_HOLD':   2, # Unlock now and remain unlocked until a lock command is received
}

CLASSIFIER_MODE = {
    'DISABLED':      0, # Disable and reset the internal state of the onboard classifier
    'ENABLED':       1, # Send classifier events (poses and arm events)
}



class EMGGUI():
    def __init__(self, device_config):  
        self.loop = asyncio.get_event_loop()
        self.data_queue = asyncio.Queue()
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.is_paused = False
        self.window_size = 1000                                      
        self.signal_time = []
        self.sample_rollover_count = 0
        self.emg_channels = 8
        self.start_time = time.time()
        self.t = 0
        self.battery_level = 0
        self.signal_strength = -0
        self.firmware_revision = '0.0.0.0'
        self.device_config = device_config
        self.device_uuid = ''
        self.client = None

        self.command_characteristic = device_config['myo_armband']['characteristics']['command']
        self.device_manufacturer_characteristic = device_config['myo_armband']['characteristics']['manufacturer']
        self.filtered_50hz_characteristic = device_config['myo_armband']['characteristics']['filtered_50hz_emg']
        self.emg_data0_characteristic = device_config['myo_armband']['characteristics']['emg0']
        self.emg_data1_characteristic = device_config['myo_armband']['characteristics']['emg1']
        self.emg_data2_characteristic = device_config['myo_armband']['characteristics']['emg2']
        self.emg_data3_characteristic = device_config['myo_armband']['characteristics']['emg3']
        self.classifier_event_characteristic = device_config['myo_armband']['characteristics']['classifier_event']
        self.device_info_characteristic = device_config['myo_armband']['characteristics']['device_info']
        self.battery_level_characteristic = device_config['myo_armband']['characteristics']['battery_level']
        self.revision_characteristic = device_config['myo_armband']['characteristics']['revision']
        
        self.emg_mode = EMG_MODE['RAW']
      
        self.emg_x_axis = []
        self.emg_y_axis = []
        self.imu_time_axis = [0.0] * self.window_size
        self.imu_gyro_x = [0.0] * self.window_size
        self.imu_gyro_y = [0.0] * self.window_size
        self.imu_gyro_z = [0.0] * self.window_size
        self.imu_accel_x = [0.0] * self.window_size
        self.imu_accel_y = [0.0] * self.window_size
        self.imu_accel_z = [0.0] * self.window_size   
        self.imu_mag_x = [0.0] * self.window_size
        self.imu_mag_y = [0.0] * self.window_size
        self.imu_mag_z = [0.0] * self.window_size             
        for _ in range(self.emg_channels):
            self.emg_x_axis.append([0.0] * self.window_size)
            self.emg_y_axis.append([0.0] * self.window_size)
        self.magnetometer_available = False

        self.yaw = 0.0
        self.pitch = 0.0
        self.roll = 0.0

        self.acc_x = 0.0
        self.acc_y = 0.0
        self.acc_z = 0.0
        self.gyr_x = 0.0
        self.gyr_y = 0.0
        self.gyr_z = 0.0
        self.mag_x = 0.0
        self.mag_y = 0.0
        self.mag_z = 0.0

        self.q = [1.0, 0.0, 0.0, 0.0]

        dpg.create_context()    

    def build_gui(self):
        with dpg.font_registry():
            font_regular_12 = dpg.add_font("fonts/Inter-Regular.ttf", 14)
            font_regular_14 = dpg.add_font("fonts/Inter-Regular.ttf", 18)
            font_regular_24 = dpg.add_font("fonts/DroidSansMono.otf", 36)         

        with dpg.theme() as data_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (26, 30, 32), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (36, 40, 42), category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 8, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 8, category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 0, category=dpg.mvThemeCat_Core)

        with dpg.theme() as stop_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (249, 122, 94), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (249, 122, 94), category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1, category=dpg.mvThemeCat_Core)

        with dpg.theme() as start_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 128, 0), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Border, (0, 128, 0), category=dpg.mvThemeCat_Core)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1, category=dpg.mvThemeCat_Core)

        with dpg.theme() as connection_connecting_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (36, 40, 42), category=dpg.mvThemeCat_Core)

        with dpg.theme() as connection_connected_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 128, 0), category=dpg.mvThemeCat_Core)

        with dpg.theme() as connection_disconnected_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (249, 122, 94), category=dpg.mvThemeCat_Core)

        with dpg.theme() as input_theme:
            with dpg.theme_component(dpg.mvAll, enabled_state=True):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 7, 9, category=dpg.mvThemeCat_Core)
            with dpg.theme_component(dpg.mvAll, enabled_state=False):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 7, 9, category=dpg.mvThemeCat_Core)

        with dpg.theme() as center_button_theme:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_style(dpg.mvStyleVar_ButtonTextAlign, 0.5, category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_Button, (36, 40, 42), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (36, 40, 42), category=dpg.mvThemeCat_Core)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (36, 40, 42), category=dpg.mvThemeCat_Core)

        with dpg.window(tag="main_window", width=1440, height=1024) as window:
            dpg.add_text("FreeMyo", pos=[40, 40])
            dpg.bind_item_font(dpg.last_item(), font_regular_24)

            dpg.add_text("Connection Status:", pos=[40, 92])
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_button(label="Disconnected", pos=[150, 90], width=150, show=True, tag="disconnected_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_disconnected_button_theme)            
            dpg.add_button(label="Connected", pos=[150, 90], width=150, show=False, tag="connected_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_connected_button_theme)            
            dpg.add_button(label="Connecting...", pos=[150, 90], width=150, show=False, tag="connecting_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_connecting_button_theme)            

            with dpg.child_window(height=100, width=200, pos=[35, 160]):
                dpg.add_text("Battery Level", pos=[10, 10])
                dpg.bind_item_theme(dpg.last_item(), center_button_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_12)
                dpg.add_button(label = self.battery_level, pos=[148, 12], width=60, tag="battery_level", small=True)
                dpg.bind_item_theme(dpg.last_item(), input_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_14)

                dpg.add_text("Signal Strength (dBm)", pos=[10, 35])
                dpg.bind_item_theme(dpg.last_item(), center_button_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_12)
                dpg.add_button(label = self.signal_strength, pos=[140, 37], width=60, tag="signal_strength_value", small=True)
                dpg.bind_item_theme(dpg.last_item(), input_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_14)       

                dpg.add_text("Firmware Version", pos=[10, 70])
                dpg.bind_item_theme(dpg.last_item(), center_button_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_12)
                dpg.add_button(label = self.firmware_revision, pos=[110, 72], width=40, tag="firmware_revision", small=True)
                dpg.bind_item_theme(dpg.last_item(), input_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_14)                               

            # dpg.add_text("IMU Signal - Accelerometer", pos=[35, 380])
            # with dpg.plot(pos=[35, 400], height=100, width=350):
            #     dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis_acc", no_tick_labels=True)
            #     dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis_acc")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_acc", tag="imu_ax")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_acc", tag="imu_ay")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_acc", tag="imu_az")

            # dpg.add_text("IMU Signal - Gyroscope", pos=[35, 510])                    
            # with dpg.plot(pos=[35, 530], height=100, width=350):
            #     dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis_gyr", no_tick_labels=True)
            #     dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis_gyr")
            #     dpg.add_line_series([], [], label="gx", parent="y_axis_gyr", tag="imu_gx")
            #     dpg.add_line_series([], [], label="gy", parent="y_axis_gyr", tag="imu_gy")
            #     dpg.add_line_series([], [], label="gz", parent="y_axis_gyr", tag="imu_gz")

            # dpg.add_text("IMU Signal - Magnetometer", pos=[35, 640])
            # with dpg.plot(pos=[35, 660], height=100, width=350):
            #     dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis_mag", no_tick_labels=True)
            #     dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis_mag")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_mag", tag="imu_mx")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_mag", tag="imu_my")
            #     dpg.add_line_series([], [], label="signal", parent="y_axis_mag", tag="imu_mz")                
            # dpg.add_text("IMU Signals", pos=[35, 380])
            # with dpg.plot(pos=[35, 400], height=300, width=350):
            #     dpg.add_plot_axis(dpg.mvXAxis, tag="x_imu", no_tick_labels=True)
            #     dpg.set_axis_limits("x_imu", 0, 30)
            #     dpg.add_plot_axis(dpg.mvYAxis, tag="y_imu")
            #     dpg.set_axis_limits("y_imu", -50,50)
            #     # dpg.add_line_series([], [], label="signal", parent="y_imu", tag="imu1")
            #     dpg.add_bar_series([], [], label="signal", weight=1, parent="y_imu", tag="imu1")

            dpg.add_text("EMG Mode", pos=[40, 300])
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_combo(("RAW", "FILTERED", "FILTERED_50HZ", "OFF"), default_value="OFF", width=140, pos=[110, 300], show=True, tag="emg_mode", callback=self.emg_mode_callback)
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            # dpg.bind_item_theme(dpg.last_item(), start_button_theme)

            dpg.add_button(label="Start", width=202, height=40, pos=[35, 340], show=True, tag="start_button",callback=self.start_collecting_data)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), start_button_theme)

            dpg.add_button(label="Stop", width=202, height=40, pos=[35, 340], show=False, tag="stop_button",callback=self.stop_collecting_data)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), stop_button_theme)

            with dpg.child_window(height=980, width=980, pos=[420, 40]):   #120
                dpg.add_text("EMG Signal 1", pos=[10, 10])
                with dpg.plot(pos=[10, 30], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis1", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis1")
                    dpg.add_line_series([], [], label="signal", parent="y_axis1", tag="signal_series1")
                dpg.add_text("EMG Signal 2", pos=[10, 130])
                with dpg.plot(pos=[10, 150], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis2", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis2")
                    dpg.add_line_series([], [], label="signal", parent="y_axis2", tag="signal_series2")
                dpg.add_text("EMG Signal 3", pos=[10, 250]) 
                with dpg.plot(pos=[10, 270], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis3", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis3")
                    dpg.add_line_series([], [], label="signal", parent="y_axis3", tag="signal_series3")
                dpg.add_text("EMG Signal 4", pos=[10, 370])
                with dpg.plot(pos=[10, 390], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis4", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis4")
                    dpg.add_line_series([], [], label="signal", parent="y_axis4", tag="signal_series4")
                dpg.add_text("EMG Signal 5", pos=[10, 490])
                with dpg.plot(pos=[10, 510], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis5", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis5")
                    dpg.add_line_series([], [], label="signal", parent="y_axis5", tag="signal_series5")
                dpg.add_text("EMG Signal 6", pos=[10, 610])
                with dpg.plot(pos=[10, 630], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis6", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis6")
                    dpg.add_line_series([], [], label="signal", parent="y_axis6", tag="signal_series6")
                dpg.add_text("EMG Signal 7", pos=[10, 730])
                with dpg.plot(pos=[10, 750], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis7", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis7")
                    dpg.add_line_series([], [], label="signal", parent="y_axis7", tag="signal_series7")
                dpg.add_text("EMG Signal 8", pos=[10, 850])
                with dpg.plot(pos=[10, 870], height=100, width=950):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis8", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis8")
                    dpg.add_line_series([], [], label="signal", parent="y_axis8", tag="signal_series8")

                       

        dpg.create_viewport(title='EMG', width=1440, height=1064, x_pos=40, y_pos=40)
        dpg.bind_item_theme(window, data_theme)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_exit_callback(self.teardown)
        dpg.set_primary_window("main_window", True)


    def emg_mode_callback(self, sender, data):
        self.emg_mode = EMG_MODE[data]
        # Command to set EMG and IMU modes
        command =  COMMAND['SET_EMG_IMU_MODE']          
        imu_mode = IMU_MODE['OFF']
        classifier_mode = CLASSIFIER_MODE['ENABLED']
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, self.emg_mode, imu_mode, classifier_mode) #  b'\x01\x02\x00\x00'
        self.loop.create_task(self.client.write_gatt_char(self.command_characteristic, command_header, response=True))
        ###########################################################################################

        if self.emg_mode == EMG_MODE['FILTERED_50HZ']:
            self.loop.create_task(self.client.start_notify(self.filtered_50hz_characteristic, self.ble_notification_callback))
        else:
            self.loop.create_task(self.client.start_notify(self.emg_data0_characteristic, self.ble_notification_callback))
            self.loop.create_task(self.client.start_notify(self.emg_data1_characteristic, self.ble_notification_callback))
            self.loop.create_task(self.client.start_notify(self.emg_data2_characteristic, self.ble_notification_callback))
            self.loop.create_task(self.client.start_notify(self.emg_data3_characteristic, self.ble_notification_callback))


    def handle_battery_notification(self, data):
        battery_level_value = int.from_bytes(data, 'little')
        self.battery_level = battery_level_value
        dpg.configure_item("battery_level", label=int(battery_level_value))

    def handle_classifier_indication(self, data):
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
        print_value += f"-- {x_direction}" if x_direction else ""
        print(print_value) 

    def ble_notification_callback(self, handle, data):
        match handle:
            case 16: # battery notifications
                self.handle_battery_notification(data)     
            case 28: # IMU data
                values = struct.unpack('10h', data)
                quat = values[:4]
                acc  = values[4:7]
                gyro = values[7:10]
                print(f"IMU: quat: {quat} acc: {acc} gyro: {gyro}")          
            case 34: # classifier notifications
                self.handle_classifier_indication(data)
            case 38: # undocumented filtered 50hz emg mode
                values = list(struct.unpack('<8h', data[:16]))
                emg = values[:8]
                intensity_candidate = int(data[15]) # This extra byte seems to be a sort of measure of intensity.
                                                    # Or a measure of how much the sensor is stretched apart.
                                                    # Maybe its the latter trying to be the former?
                                                    # The values vary from 0 to 7 and seem to rise with intensity of pose.
                                                    # This is really only noticeable when making a fist (perhaps because all the muscles tense)
                print(f"EMG: {emg} - Intensity: {intensity_candidate}")
            case 42: # EMG 0
                emg0 = struct.unpack('<16b', data)
                print(f"EMG 0: {emg0}")
                # emg1 = struct.unpack('<8b', data[:8])
                # emg2 = struct.unpack('<8b', data[8:])
                # print(emg1)
                # print(emg2)
            case 45: # EMG 1
                emg1 = struct.unpack('<16b', data) 
                print(f"EMG 1: {emg1}")        
                # emg3 = struct.unpack('<8b', data[:8])
                # emg4 = struct.unpack('<8b', data[8:])
                # print(emg3)
                # print(emg4)
            case 48: # EMG 2
                emg2 = struct.unpack('<16b', data)    
                print(f"EMG 2: {emg2}")   
                # emg5 = struct.unpack('<8b', data[:8])
                # emg6 = struct.unpack('<8b', data[8:])
                # print(emg5)
                # print(emg6)
            case 51: # EMG 3
                emg3 = struct.unpack('<16b', data)  
                print(f"EMG 3: {emg3}")   
                # emg7 = struct.unpack('<8b', data[:8])
                # emg8 = struct.unpack('<8b', data[8:])
                # print(emg7)
                # print(emg8)
            case _:
                print(f"Unknown Characteristic: Handle: {handle} Data: {data}")

    async def run(self):
        asyncio.create_task(self.collect_emg_data())           
        while dpg.is_dearpygui_running():
            await asyncio.sleep(0.001)
            # await self.update_plots()
            dpg.render_dearpygui_frame()
        await asyncio.sleep(0.01)
        self.running = False
        self.shutdown_event.set() 
        time.sleep(0.1)      
        dpg.destroy_context()


    def start_collecting_data(self):
        self.running = True
        self.start_time = time.time()        
        dpg.configure_item("start_button", show=False)
        dpg.configure_item("stop_button", show=True)


    def stop_collecting_data(self):
        self.running = False    
        dpg.configure_item("start_button", show=True)
        dpg.configure_item("stop_button", show=False)


    # async def update_plots(self):
    #     current_queue_size = self.data_queue.qsize()
    #     if self.running == True and current_queue_size > 0:
    #         incoming_data = await self.data_queue.get()
    #         sample_count = incoming_data['sample_count']
    #         self.t = incoming_data['time'] - self.start_time 

    #         for current_sample in range(sample_count):              
    #             samples = incoming_data['samples'][current_sample]
    #             emg_samples = samples[0:8]          

    #             for index,value in enumerate(emg_samples):
    #                 emg_data_point = float(value)
    #                 if index >= 0 and index <= (self.emg_channels - 1):
    #                     self.emg_x_axis[index].append(self.t)
    #                     self.emg_x_axis[index] = self.emg_x_axis[index][-self.window_size:]                
    #                     self.emg_y_axis[index].append(emg_data_point)
    #                     self.emg_y_axis[index] = self.emg_y_axis[index][-self.window_size:]   
    #                     plot_tag = 'signal_series' + str(index + 1)
    #                     dpg.set_value(plot_tag, [self.emg_x_axis[index], self.emg_y_axis[index]])
    #                     x_axis_tag = 'x_axis' + str(index + 1)
    #                     dpg.fit_axis_data(x_axis_tag)
    #                     y_axis_tag = 'y_axis' + str(index + 1)
    #                     dpg.set_axis_limits(y_axis_tag, -200, 200)    

    #             self.imu_time_axis.append(self.t)
    #             self.imu_time_axis = self.imu_time_axis[-self.window_size:]  

    #             self.imu_gyro_x.append(self.gyr_x)
    #             self.imu_gyro_x = self.imu_gyro_x[-self.window_size:] 
    #             self.imu_gyro_y.append(self.gyr_y)
    #             self.imu_gyro_y = self.imu_gyro_y[-self.window_size:] 
    #             self.imu_gyro_z.append(self.gyr_z)
    #             self.imu_gyro_z = self.imu_gyro_z[-self.window_size:]   

    #             dpg.set_value("imu_gx", [self.imu_time_axis, self.imu_gyro_x])
    #             dpg.set_value("imu_gy", [self.imu_time_axis, self.imu_gyro_y])
    #             dpg.set_value("imu_gz", [self.imu_time_axis, self.imu_gyro_z])
    #             dpg.fit_axis_data("x_axis_gyr")
    #             dpg.set_axis_limits("y_axis_gyr", -50,50)                

    #             self.imu_accel_x.append(self.acc_x)
    #             self.imu_accel_x = self.imu_accel_x[-self.window_size:] 
    #             self.imu_accel_y.append(self.acc_y)
    #             self.imu_accel_y = self.imu_accel_y[-self.window_size:] 
    #             self.imu_accel_z.append(self.acc_z)
    #             self.imu_accel_z = self.imu_accel_z[-self.window_size:]                                 

    #             dpg.set_value("imu_ax", [self.imu_time_axis, self.imu_accel_x])
    #             dpg.set_value("imu_ay", [self.imu_time_axis, self.imu_accel_y])
    #             dpg.set_value("imu_az", [self.imu_time_axis, self.imu_accel_z])
    #             dpg.fit_axis_data("x_axis_acc")
    #             dpg.set_axis_limits("y_axis_acc", -1,1.2)

    #             self.imu_mag_x.append(self.mag_x)
    #             self.imu_mag_x = self.imu_mag_x[-self.window_size:] 
    #             self.imu_mag_y.append(self.mag_y)
    #             self.imu_mag_y = self.imu_mag_y[-self.window_size:] 
    #             self.imu_mag_z.append(self.mag_z)
    #             self.imu_mag_z = self.imu_mag_z[-self.window_size:]
    #             dpg.set_value("imu_mx", [self.imu_time_axis, self.imu_mag_x])
    #             dpg.set_value("imu_my", [self.imu_time_axis, self.imu_mag_y])
    #             dpg.set_value("imu_mz", [self.imu_time_axis, self.imu_mag_z])
    #             dpg.fit_axis_data("x_axis_mag")
    #             dpg.fit_axis_data("y_axis_mag")

 

    async def collect_emg_data(self):
        self.device_uuid = self.device_config['myo_armband']['device_uuid']
        print(f"Connecting to {self.device_uuid}")
        dpg.configure_item("disconnected_button", show=False)
        dpg.configure_item("connected_button", show=False)
        dpg.configure_item("connecting_button", show=True)

        try:
            async with BleakClient(self.device_uuid) as client:
                dpg.configure_item("disconnected_button", show=False)
                dpg.configure_item("connecting_button", show=False) 
                dpg.configure_item("connected_button", show=True)
                self.client = client

                # Get signal strength
                rssi = await client.get_rssi()
                dpg.configure_item("signal_strength_value", label=int(rssi))

                # Get battery level and subscribe to notifications for it
                battery_level_char = await client.read_gatt_char(self.battery_level_characteristic)
                self.battery_level = int.from_bytes(battery_level_char, 'big')
                print(f"Battery Level: {self.battery_level}")
                dpg.configure_item("battery_level", label=int(self.battery_level))
                await client.start_notify(self.battery_level_characteristic, self.ble_notification_callback)

                # Get firmware version
                firmware_revision_value = await client.read_gatt_char(self.revision_characteristic)
                major = int.from_bytes(firmware_revision_value[0:2], 'little') # Major
                minor = int.from_bytes(firmware_revision_value[2:4], 'little') # Minor
                patch = int.from_bytes(firmware_revision_value[4:6], 'little') # Patch
                hardware_revision = int.from_bytes(firmware_revision_value[6:8], 'little') # Hardware Revision
                self.firmware_revision = f"{major}.{minor}.{patch}.{hardware_revision}"                       
                dpg.configure_item("firmware_revision", label=self.firmware_revision)

                # Get serial number
                device_info_char = await client.read_gatt_char(self.device_info_characteristic)
                info = struct.unpack("<6BHBBBBB7B", device_info_char)
                serial_number = '-'.join(map(str, info[0:6]))
                print(f"Serial Number: {serial_number}")
                                
                # Set the LED to a very nice purple
                command = COMMAND['LED'] 
                payload = [128, 128, 255, 128, 128, 255] # first 3 bytes is the logo color, second 3 bytes is the bar color
                payload_byte_size = len(payload)
                command_header = struct.pack('<8B', command, payload_byte_size, *payload) 
                await client.write_gatt_char(self.command_characteristic, command_header, response=True)
                            
                # send a short vibration to signify connection
                command = COMMAND['VIBRATE'] 
                vibration_type = VIBRATION_DURATION['SHORT']
                payload_byte_size = 1
                command_header = struct.pack('<3B', command, payload_byte_size, vibration_type)
                await client.write_gatt_char(self.command_characteristic, command_header, response=True)      
                


                try:
                    while not self.shutdown_event.is_set():
                        await asyncio.sleep(1)

                except Exception as e:
                    print(e)
                    self.teardown()
            dpg.configure_item("connecting_button", show=False) 
            dpg.configure_item("connected_button", show=False)
            dpg.configure_item("disconnected_button", show=True)            
        except BleakError as be:
            print(be)
            self.teardown()

                

    def teardown(self):
        try:
            dpg.configure_item("connecting_button", show=False) 
            dpg.configure_item("connected_button", show=False)
            dpg.configure_item("disconnected_button", show=True)                 
            self.running = False
            self.shutdown_event.set()
            time.sleep(0.1)
            for task in asyncio.all_tasks():
                task.cancel()
            loop = asyncio.get_event_loop()
            loop.stop()            
        except:
            pass    

  

async def main():
    with open("myo_config.yaml", "r") as stream:
        try:
            device_config = yaml.safe_load(stream)
        except Exception as e:
            print(f"Error reading config file: {e}")
            return
    emg = EMGGUI(device_config)
    emg.build_gui()
    await emg.run()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, RuntimeError):
        pass
