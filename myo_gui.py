import asyncio, time, struct, yaml
import dearpygui.dearpygui as dpg
from bleak import BleakClient, BleakError
import pymysql.cursors
import random

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
        self.emg_data_queue = asyncio.Queue()
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.is_paused = False
        self.window_size = 200 * 30 # 200 Hz * 30 seconds
        self.emg_channels = 8
        self.start_time = time.time()
        self.t = 0
        self.battery_level = 0
        self.signal_strength = 0
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

        self.database = {}
        self.database['host'] = device_config['database']['host']
        self.database['port'] = device_config['database']['port']
        self.database['user'] = device_config['database']['user']
        self.database['password'] = device_config['database']['password']
        self.database['schema'] = device_config['database']['schema']
        self.database['table'] = device_config['database']['table']

        self.batch_start_time = 0
        
        self.emg_mode = EMG_MODE['OFF']
        self.classifier_mode = CLASSIFIER_MODE['DISABLED']
        self.imu_mode = IMU_MODE['OFF']
      
        self.emg_x_axis = []
        self.emg_y_axis = []
        for _ in range(self.emg_channels):
            self.emg_x_axis.append([0] * self.window_size)
            self.emg_y_axis.append([0] * self.window_size)

        self.db_connection = None
        self.db_connected = False

        dpg.create_context()    

    def build_gui(self):
        with dpg.font_registry():
            font_regular_12 = dpg.add_font("fonts/SF-Pro-Display-Regular.otf", 14)
            font_regular_14 = dpg.add_font("fonts/SF-Pro-Display-Regular.otf", 18)
            font_regular_24 = dpg.add_font("fonts/SF-Pro-Display-Regular.otf", 36)         

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

        
        x_pos = 40
        y_pos = 0
        with dpg.window(tag="main_window", width=1440, height=1024) as window:            
            y_pos += 40
            dpg.add_text("FreeMyo", pos=[x_pos, y_pos])
            dpg.bind_item_font(dpg.last_item(), font_regular_24)

            y_pos += 50
            dpg.add_text("Connection Status:", pos=[x_pos, y_pos+2])
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_button(label="Disconnected", pos=[x_pos+115, y_pos], width=150, show=True, tag="disconnected_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_disconnected_button_theme)            
            dpg.add_button(label="Connected", pos=[x_pos+115, y_pos], width=150, show=False, tag="connected_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_connected_button_theme)            
            dpg.add_button(label="Connecting...", pos=[x_pos+115, y_pos], width=150, show=False, tag="connecting_button")
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), connection_connecting_button_theme)            

            y_pos += 50
            with dpg.child_window(height=100, width=200, pos=[x_pos-5, y_pos]):
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

            y_pos += 140
            dpg.add_text("EMG Mode", pos=[x_pos, y_pos])
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_combo(("RAW", "FILTERED", "FILTERED_50HZ", "OFF"), default_value="OFF", width=140, pos=[x_pos+70, y_pos-2], show=True, tag="emg_mode", callback=self.emg_mode_callback)
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)

            y_pos += 40
            dpg.add_text("Classifier Mode", pos=[x_pos, y_pos])
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_combo(("ENABLED", "DISABLED"), default_value="DISABLED", width=115, pos=[x_pos+95, y_pos-2], show=True, tag="classifier_mode", callback=self.classifier_mode_callback)
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)

            y_pos += 40
            dpg.add_text("IMU Mode", pos=[x_pos, y_pos])
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_combo(("OFF", "SEND_DATA", "SEND_EVENTS", "SEND_ALL", "SEND_RAW"), default_value="OFF", width=140, pos=[x_pos+70, y_pos-2], show=True, tag="imu_mode", callback=self.imu_mode_callback)
            dpg.bind_item_theme(dpg.last_item(), center_button_theme)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)

            y_pos += 70
            dpg.add_text("Pose", pos=[x_pos, y_pos])
            dpg.bind_item_font(dpg.last_item(), font_regular_12)
            dpg.add_button(label = "REST", pos=[x_pos+35, y_pos+2], width=60, tag="pose_display", small=True)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), input_theme)

            y_pos += 60
            with dpg.child_window(height=100, width=300, pos=[x_pos-5, y_pos]):    
                dpg.add_text("Database Status:", pos=[12, 10])
                dpg.bind_item_font(dpg.last_item(), font_regular_12)  
                dpg.add_button(label="Disconnected", pos=[125, 10], width=150, show=True, tag="disconnected_database_button")
                dpg.bind_item_font(dpg.last_item(), font_regular_14)
                dpg.bind_item_theme(dpg.last_item(), connection_disconnected_button_theme)            
                dpg.add_button(label="Connected", pos=[125, 10], width=150, show=False, tag="connected_database_button")
                dpg.bind_item_font(dpg.last_item(), font_regular_14)
                dpg.bind_item_theme(dpg.last_item(), connection_connected_button_theme)                        
                dpg.add_button(label="Connect", pos=[10, 40], width=60, tag="database_button", small=True, callback=self.db_connect)
                dpg.bind_item_theme(dpg.last_item(), input_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_14)
                dpg.add_button(label="Disconnect", pos=[10, 70], width=60, tag="database_button2", small=True, callback=self.db_disconnect)
                dpg.bind_item_theme(dpg.last_item(), input_theme)
                dpg.bind_item_font(dpg.last_item(), font_regular_14)            

            y_pos += 400
            dpg.add_button(label="Deep Sleep", width=120, height=40, pos=[x_pos, y_pos], show=True, tag="sleep_button",callback=self.put_to_sleep)
            dpg.bind_item_font(dpg.last_item(), font_regular_14)
            dpg.bind_item_theme(dpg.last_item(), stop_button_theme)


            x_pos = 420
            y_pos = 40
            with dpg.child_window(height=980, width=980, pos=[x_pos, y_pos]):
                graph_x_pos = 10
                graph_height = 100
                graph_width = 950
                dpg.add_text("EMG Signal 1", pos=[graph_x_pos, 10])
                with dpg.plot(pos=[graph_x_pos, 30], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis1", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis1")
                    dpg.add_line_series([], [], label="signal", parent="y_axis1", tag="signal_series1")      
                dpg.add_text("EMG Signal 2", pos=[graph_x_pos, 130])
                with dpg.plot(pos=[graph_x_pos, 150], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis2", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis2")
                    dpg.add_line_series([], [], label="signal", parent="y_axis2", tag="signal_series2")
                dpg.add_text("EMG Signal 3", pos=[graph_x_pos, 250]) 
                with dpg.plot(pos=[graph_x_pos, 270], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis3", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis3")
                    dpg.add_line_series([], [], label="signal", parent="y_axis3", tag="signal_series3")
                dpg.add_text("EMG Signal 4", pos=[graph_x_pos, 370])
                with dpg.plot(pos=[graph_x_pos, 390], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis4", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis4")
                    dpg.add_line_series([], [], label="signal", parent="y_axis4", tag="signal_series4")
                dpg.add_text("EMG Signal 5", pos=[graph_x_pos, 490])
                with dpg.plot(pos=[graph_x_pos, 510], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis5", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis5")
                    dpg.add_line_series([], [], label="signal", parent="y_axis5", tag="signal_series5")
                dpg.add_text("EMG Signal 6", pos=[graph_x_pos, 610])
                with dpg.plot(pos=[graph_x_pos, 630], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis6", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis6")
                    dpg.add_line_series([], [], label="signal", parent="y_axis6", tag="signal_series6")
                dpg.add_text("EMG Signal 7", pos=[graph_x_pos, 730])
                with dpg.plot(pos=[graph_x_pos, 750], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis7", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis7")
                    dpg.add_line_series([], [], label="signal", parent="y_axis7", tag="signal_series7")
                dpg.add_text("EMG Signal 8", pos=[graph_x_pos, 850])
                with dpg.plot(pos=[graph_x_pos, 870], height=graph_height, width=graph_width):
                    dpg.add_plot_axis(dpg.mvXAxis, tag="x_axis8", no_tick_labels=True)
                    dpg.add_plot_axis(dpg.mvYAxis, tag="y_axis8")
                    dpg.add_line_series([], [], label="signal", parent="y_axis8", tag="signal_series8")


        dpg.create_viewport(title='EMG', width=1440, height=1064, x_pos=40, y_pos=40)
        dpg.bind_item_theme(window, data_theme)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.set_exit_callback(self.teardown)
        dpg.set_primary_window("main_window", True)


    def db_connect(self):
        try:
            self.db_connection = pymysql.connect(host=self.database['host'],
                                            user=self.database['user'],
                                            db=self.database['schema'],
                                            charset='utf8mb4',
                                            cursorclass=pymysql.cursors.DictCursor)
            if self.db_connection: 
                self.db_connected = True
                self.batch_start_time = int(time.time())
                dpg.configure_item("disconnected_database_button", show=False)
                dpg.configure_item("connected_database_button", show=True)                  
        except Exception as e:
            print(e)

    def db_disconnect(self):
        try:
            self.db_connection.close()
            self.db_connected = False
            dpg.configure_item("disconnected_database_button", show=True)
            dpg.configure_item("connected_database_button", show=False)            
        except Exception as e:
            print(e)            
        
    def write_to_db(self, time, emg_sensor_data: list):
        # pass
        with self.db_connection.cursor() as cursor:
                sql = """
                    INSERT INTO `data`
                    (`time`,`emg_sensor_1`,`emg_sensor_2`,`emg_sensor_3`,`emg_sensor_4`,`emg_sensor_5`,`emg_sensor_6`,`emg_sensor_7`,`emg_sensor_8`, `batch_start_time`) 
                    VALUES 
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                cursor.execute(sql, 
                    (
                    time,
                    emg_sensor_data[0],
                    emg_sensor_data[1],
                    emg_sensor_data[2],
                    emg_sensor_data[3],
                    emg_sensor_data[4],
                    emg_sensor_data[5],
                    emg_sensor_data[6],
                    emg_sensor_data[7],
                    self.batch_start_time,
                    )
                )
        self.db_connection.commit()

    def read_from_db(self):
        pass
        # with self.db_connection.cursor() as cursor:
        #     sql = "SELECT * FROM `data`"
        #     cursor.execute(sql)
        #     result = cursor.fetchone()
        #     print(result)        

    def put_to_sleep(self, sender, data):
        # Deep sleep command ######################################################################
        # WARNING: This will immediately disconnect and put the Myo into a deep sleep that can only 
        # be awakened by plugging it into USB
        command = COMMAND['DEEP_SLEEP'] 
        payload_byte_size = 1
        command_header = struct.pack('<2B', command, payload_byte_size)
        self.loop.create_task(self.client.write_gatt_char(self.command_characteristic, command_header, response=True))
        ###########################################################################################



    def imu_mode_callback(self, sender, data):
        old_mode = self.imu_mode
        self.imu_mode = IMU_MODE[data]

        # Command to set EMG, IMU, and CLASSIFIER modes
        command =  COMMAND['SET_EMG_IMU_MODE']          
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, self.emg_mode, self.imu_mode, self.classifier_mode) #  b'\x01\x02\x00\x00'
        self.loop.create_task(self.client.write_gatt_char(self.command_characteristic, command_header, response=True))
        ###########################################################################################
        # TODO: Implement IMU mode 
        print("IMU Mode not implemented yet.")


    def classifier_mode_callback(self, sender, data):
        old_mode = self.classifier_mode
        self.classifier_mode = CLASSIFIER_MODE[data]

        # Command to set EMG, IMU, and CLASSIFIER modes
        command =  COMMAND['SET_EMG_IMU_MODE']          
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, self.emg_mode, self.imu_mode, self.classifier_mode) #  b'\x01\x02\x00\x00'
        self.loop.create_task(self.client.write_gatt_char(self.command_characteristic, command_header, response=True))
        ###########################################################################################
        if old_mode == CLASSIFIER_MODE['DISABLED'] and self.classifier_mode == CLASSIFIER_MODE['ENABLED']:
            self.loop.create_task(self.client.start_notify(self.classifier_event_characteristic, self.ble_notification_callback))
        elif old_mode == CLASSIFIER_MODE['ENABLED'] and self.classifier_mode == CLASSIFIER_MODE['DISABLED']:
            self.loop.create_task(self.client.stop_notify(self.classifier_event_characteristic))
        


    def emg_mode_callback(self, sender, data):
        old_mode = self.emg_mode
        self.emg_mode = EMG_MODE[data]

        # Command to set EMG, IMU, and CLASSIFIER modes
        command =  COMMAND['SET_EMG_IMU_MODE']          
        imu_mode = IMU_MODE['OFF']
        classifier_mode = CLASSIFIER_MODE['ENABLED']
        payload_byte_size = 3
        command_header = struct.pack('<5B', command, payload_byte_size, self.emg_mode, imu_mode, classifier_mode) #  b'\x01\x02\x00\x00'
        self.loop.create_task(self.client.write_gatt_char(self.command_characteristic, command_header, response=True))
        ###########################################################################################
        
        if self.emg_mode in [EMG_MODE['RAW'], EMG_MODE['FILTERED']]:
            self.running = True
            if old_mode == EMG_MODE['OFF']:
                self.loop.create_task(self.client.start_notify(self.emg_data0_characteristic, self.ble_notification_callback))
                self.loop.create_task(self.client.start_notify(self.emg_data1_characteristic, self.ble_notification_callback))
                self.loop.create_task(self.client.start_notify(self.emg_data2_characteristic, self.ble_notification_callback))
                self.loop.create_task(self.client.start_notify(self.emg_data3_characteristic, self.ble_notification_callback))
        elif self.emg_mode == EMG_MODE['OFF']:
            self.running = False
            self.loop.create_task(self.client.stop_notify(self.emg_data0_characteristic))
            self.loop.create_task(self.client.stop_notify(self.emg_data1_characteristic))
            self.loop.create_task(self.client.stop_notify(self.emg_data2_characteristic))
            self.loop.create_task(self.client.stop_notify(self.emg_data3_characteristic))             
        elif self.emg_mode == EMG_MODE['FILTERED_50HZ']:
            self.running = True
            self.loop.create_task(self.client.start_notify(self.filtered_50hz_characteristic, self.ble_notification_callback))            

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
                classifier_value = 'UNSYNCED'
            case 'POSE':
                classifier_value = POSE_VALUES[value_id]
            case 'UNLOCKED':
                classifier_value = 'UNLOCKED'
            case 'LOCKED':
                classifier_value = 'LOCKED'
            case 'SYNC_FAILED':
                classifier_value = 'SYNC_FAILED'
            case _:
                classifier_event = "Unknown Event"
        # print_value = f"{classifier_value} " if classifier_value else ""
        # print_value += f"-- {x_direction}" if x_direction else ""
        # print(print_value) 
        dpg.configure_item("pose_display", label=classifier_value)

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
                emg0 = list(struct.unpack('<16b', data))
                emg0.append(0)
                self.loop.create_task(self.emg_data_queue.put(emg0))
            case 45: # EMG 1
                emg1 = list(struct.unpack('<16b', data))
                emg1.append(1)
                self.loop.create_task(self.emg_data_queue.put(emg1))
            case 48: # EMG 2
                emg2 = list(struct.unpack('<16b', data))
                emg2.append(2)
                self.loop.create_task(self.emg_data_queue.put(emg2))
            case 51: # EMG 3
                emg3 = list(struct.unpack('<16b', data))
                emg3.append(3)
                self.loop.create_task(self.emg_data_queue.put(emg3))
            case _:
                print(f"Unknown Characteristic: Handle: {handle} Data: {data}")

    async def run(self):
        asyncio.create_task(self.collect_emg_data())
        asyncio.create_task(self.process_emg_data())
        asyncio.create_task(self.update_plots())
        while dpg.is_dearpygui_running():
            await asyncio.sleep(0.001)
            dpg.render_dearpygui_frame()
        await asyncio.sleep(0.01)
        self.running = False
        self.shutdown_event.set() 
        time.sleep(0.1)      
        dpg.destroy_context()

    async def process_emg_data(self):
        try:        
            last_recv_characteristic = 0
            while not self.shutdown_event.is_set():
                # print(self.emg_data_queue.qsize())
                if self.running == True and self.emg_data_queue.qsize() > 0:
                    incoming_data = await self.emg_data_queue.get()

                    emg1 = incoming_data[:8]
                    emg2 = incoming_data[8:16]
                    recv_characteristic = incoming_data[16]
                    
                    progression = (recv_characteristic - last_recv_characteristic) % 4
                    if progression > 1:
                        for i in range(1,progression):
                            # print("packet not received")
                            self.t += 5
                            for _ in range(1,8):
                                self.emg_x_axis[i].append(self.t)
                                self.emg_y_axis[i].append(0)

                            if self.db_connected:
                                self.write_to_db(self.t, [0] * 8)
                    last_recv_characteristic = recv_characteristic
                    
                    self.t += 10
                    for i in range(0,8):
                        self.emg_x_axis[i].append(self.t - 5)
                        self.emg_x_axis[i].append(self.t)
                        self.emg_y_axis[i].append(emg1[i])
                        self.emg_y_axis[i].append(emg2[i])

                    if self.db_connected:
                        self.write_to_db(self.t, emg1)
                        self.write_to_db(self.t, emg2)

                else:
                    await asyncio.sleep(0.0001)
        except KeyboardInterrupt:
            pass
 

    async def update_plots(self):
        try:
            while not self.shutdown_event.is_set():
                await asyncio.sleep(0.01)
                for i in range(0,8):
                    self.emg_x_axis[i] = self.emg_x_axis[i][-self.window_size:]
                    self.emg_y_axis[i] = self.emg_y_axis[i][-self.window_size:] 
                    dpg.set_value('signal_series' + str(i + 1), [self.emg_x_axis[i], self.emg_y_axis[i]])
                    dpg.fit_axis_data(   'x_axis' + str(i + 1))
                    dpg.set_axis_limits( 'y_axis' + str(i + 1), -150, 150) 
        except KeyboardInterrupt:
            pass
 

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
                                
                # # Unlock command ######################################################################
                # command = COMMAND['UNLOCK']
                # lock_mode = UNLOCK_COMMAND['UNLOCK_HOLD']
                # payload_byte_size = 1
                # command_header = struct.pack('<3B', command, payload_byte_size, lock_mode)
                # await client.write_gatt_char(self.command_characteristic, command_header, response=True)      
                # #######################################################################################


                # Set the LED to a very nice purple
                command = COMMAND['LED']
                payload = [128, 128, 255, 128, 128, 255] # first 3 bytes is the logo color, second 3 bytes is the bar color
                payload_byte_size = len(payload)
                command_header = struct.pack('<8B', command, payload_byte_size, *payload)
                await client.write_gatt_char(self.command_characteristic, command_header, response=True)
                            
                # # send a short vibration to signify connection
                command = COMMAND['VIBRATE'] 
                vibration_type = VIBRATION_DURATION['SHORT']
                payload_byte_size = 1
                command_header = struct.pack('<3B', command, payload_byte_size, vibration_type)
                await client.write_gatt_char(self.command_characteristic, command_header, response=True)      
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
    except (KeyboardInterrupt): #, RuntimeError):
        pass
