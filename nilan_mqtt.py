import logging.handlers
from tzlocal import get_localzone
import json
import config
import os
import time
from datetime import datetime
import paho.mqtt.client as paho
from pymodbus.client.sync import ModbusSerialClient as ModbusClient

version = "0.2"
log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), config.mqtt_host_id +'.log')
print(log_file)
logging.basicConfig(filename=log_file,
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.INFO)


def run_act_mapping(value):
    if value == 0:
        return 'Off'
    else:
        return 'On'


def mode_act_mapping(value):
    if value == 0:
        return 'Off'
    elif value == 1:
        return 'Heat'
    elif value == 2:
        return 'Cool'
    elif value == 3:
        return 'Auto'
    else:
        return 'Service'


def state_mapping(value):
    if value == 0:
        return 'Off'
    elif value == 1:
        return 'Shift'
    elif value == 2:
        return 'Stop'
    elif value == 3:
        return 'Start'
    elif value == 4:
        return 'Standby'
    elif value == 5:
        return 'Ventilation stop'
    elif value == 6:
        return 'Ventilation'
    elif value == 7:
        return 'Heating'
    elif value == 8:
        return 'Cooling'
    elif value == 9:
        return 'Hot water'
    elif value == 10:
        return 'Legionella'
    elif value == 11:
        return 'Cooling + hot water'
    elif value == 12:
        return 'Central heating'
    elif value == 13:
        return 'Defrost'
    elif value == 14:
        return 'Frost secure'
    elif value == 15:
        return 'Service'
    else:
        return 'Alarm'


def read_registers(start_reg, nr_of_regs, function):
    modbus_client = ModbusClient(method='rtu', port=config.modbus_port, stopbits=1, bytesize=8, parity=config.parity, baudrate=19200)
    if function == 'input registers':
        val = modbus_client.read_input_registers(start_reg, nr_of_regs, unit=30)
    else:
        val = modbus_client.read_holding_registers(start_reg, nr_of_regs, unit=30)

    if not val.isError():
        return True, val.registers
    else:
        logging.warning("error: {}".format(val))
        return False, ''

def get_timestamp():
    ts_message = datetime.now().astimezone(get_localzone()).strftime('%Y-%m-%d %H:%M:%S%z')

    ts_message = "{0}:{1}".format(
        ts_message[:-2],
        ts_message[-2:]
    )
    return ts_message


def config_json(key, topic_prefix, host, device_name):
                data = {
                        "device": {
                        "identifiers": ["123456"],
                        "manufacturer" : "NILAN",
                        "model" : "Nilan Comfort 300",
                        "name" : device_name,
                    },
                        "state_topic": "",
                        "icon": "",
                        "name": "",
                        "unique_id": "",
                        "unit_of_measurement": "",
                }

                data["state_topic"] = topic_prefix + "/"+ host + "/" + key
                
                data["unique_id"] = host +"_"+key
                
                if key == "t0_controller":
                        data["icon"] = "mdi:thermometer"
                        data["name"] = device_name + " Controller Board Temperature"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"
                        
                elif key == "t3_exhaust":
                        data["icon"] = "mdi:thermometer"
                        data["name"] = device_name + " Exhaust Temperature At In Take"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"
                        
                elif key == "t4_outlet":
                        data["icon"] = "mdi:thermometer"
                        data["name"] = device_name + " Outlet Temperature"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"
                        
                elif key == "t7_inlet":
                        data["icon"] = "mdi:thermometer"
                        data["name"] = device_name + " Inlet Temperature After Heating Surface"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"

                elif key == "t8_outdoor":
                        data["icon"] = "mdi:sun-thermometer-outline"
                        data["name"] = device_name + " Outdoor Air Temperature At Intake"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"
                        
                elif key == "t15_room":
                        data["icon"] = "mdi:home-thermometer-outline"
                        data["name"] = device_name + " Temperature At Control Panel"
                        data["unit_of_measurement"] = "°C"
                        data["state_class"] = "measurement"
                        data["device_class"] = "temperature"
                                                
                elif key == "rh":
                        data["icon"] = "mdi:water-percent"
                        data["name"] = device_name + " Relative Humidity"   
                        data["unit_of_measurement"] = "%"
                        data["device_class"] = "humidity"
                        data["state_class"] = "measurement"
                                                
                elif key == "run_state":
                        data["icon"] =  "mdi:fan"
                        data["name"] = device_name + " Running State"                  
                        
                elif key == "operation_mode":
                        data["icon"] =  "mdi:cog"
                        data["name"] = device_name + " Operation Mode"                   
                        
                elif key == "control_state":
                        data["icon"] =  "mdi:state-machine"
                        data["name"] = device_name + " Control State"                  
                        
                elif key == "passive_heat_exchanger_efficiency":
                        data["unit_of_measurement"] = "%"
                        data["icon"] =  "mdi:swap-horizontal"
                        data["name"] = device_name + " Passive Heat Exchanger Efficiency"                  
                        
                elif key == "air_temperature_actual_capacity":
                        data["unit_of_measurement"] = "%"
                        data["icon"] =  "mdi:thermometer-lines"
                        data["name"] = device_name + " Air Temperature Actual Capacity"                  
                        
                elif key == "exhaust_fan_speed":
                        data["icon"] =  "mdi:speedometer"
                        data["name"] = device_name + " Exhaust Fan Speed"                  
                        
                elif key == "inlet_fan_speed":
                        data["icon"] =  "mdi:speedometer"
                        data["name"] = device_name + " Inlet Fan Speed"          
                             
                elif key == "update":
                        data["icon"] =  "mdi:update"
                        data["name"] = device_name + " Updated At"
                        data["device_class"] = "timestamp"
                else:
                        return None
                       
                # Return our built discovery config
                return json.dumps(data)

def publish_to_mqtt(key, value, topic_prefix, host, device_name):
    
                json_send = config_json(key, topic_prefix, host, device_name)
                        
                if(json_send is not None):
                        client = paho.Client()
                        client.username_pw_set(config.mqtt_user, config.mqtt_password)
                        client.connect(config.mqtt_host, int(config.mqtt_port))
                        if config.discovery_messages:
                                client.publish("homeassistant/sensor/"+ topic_prefix +"/"+host+"_"+ key +"/config",json_send, qos=0)

                        client.publish(topic_prefix +"/"+host+"/"+ key, value, qos=1)
                        client.disconnect()
                else:
                        logging.warning(key + " not configured")

while True:
    total_read_succeed = True
    
    read_result = []
    read_succeed, value = read_registers(200, 22, 'input registers')
    if read_succeed:
        publish_to_mqtt(key = "t0_controller", value = int(value[0]) / 100, topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "t3_exhaust", value = int(value[3]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "t4_outlet", value = int(value[4]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "t7_inlet", value = int(value[7]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "t8_outdoor", value = int(value[8]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "t15_room", value = int(value[15]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "rh", value = int(value[21]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
    
    else:
        total_read_succeed = False

    read_succeed, value = read_registers(1000, 3, 'input registers')
    if read_succeed:
        publish_to_mqtt(key = "run_state", value = run_act_mapping(value[0]),topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "operation_mode", value = mode_act_mapping(value[1]),topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "control_state", value = state_mapping(value[2]),topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)

    else:
        total_read_succeed = False

    read_succeed, value = read_registers(1204, 3, 'input registers')
    if read_succeed:
        publish_to_mqtt(key = "passive_heat_exchanger_efficiency", value = int(value[0]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "air_temperature_actual_capacity", value = int(value[2]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
    else:
        total_read_succeed = False

    read_succeed, value = read_registers(200, 2, 'holding registers')
    if read_succeed:
        publish_to_mqtt(key = "exhaust_fan_speed", value = int(value[0]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        publish_to_mqtt(key = "inlet_fan_speed", value = int(value[1]) / 100,topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
    else:
        total_read_succeed = False

    if total_read_succeed:
        publish_to_mqtt(key = "update", value = get_timestamp(),topic_prefix = config.mqtt_topic_prefix , host = config.mqtt_host_id, device_name = config.mqtt_device_name)
        sleepTime = 10
    else:
        logging.warning('Failed to read from modbus, retry in 10sec')
        sleepTime = 10

    time.sleep(sleepTime)
    