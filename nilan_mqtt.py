import logging.handlers
from tzlocal import get_localzone
import json
import config
import os
import time
from datetime import datetime
import paho.mqtt.client as paho
import requests
from ast import literal_eval

# from pymodbus.client.sync import ModbusSerialClient as ModbusClient

version = "0.3"
log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), config.mqtt_host_id + '.log')
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


def get_timestamp():
    ts_message = datetime.now().astimezone(get_localzone()).strftime('%Y-%m-%d %H:%M:%S%z')

    ts_message = "{0}:{1}".format(
        ts_message[:-2],
        ts_message[-2:]
    )
    return ts_message


def config_json(reg_data, topic_prefix, host, device_name):
    mqtt_data = {
        "device": {
            "identifiers": ["123456"],
            "manufacturer": "NILAN",
            "model": "Nilan Comfort 300",
            "name": device_name,
        },
        "state_topic": topic_prefix + "/" + host + "/" + reg_data['datapoint_key'],
        "icon": reg_data['icon'],
        "name": device_name + " " + reg_data['sensor_name'],
        "unique_id": host + "_" + reg_data['datapoint_key'],
        "unit_of_measurement": reg_data['unit_of_measurement'],
        "state_class": reg_data['state_class'],
        "device_class": reg_data['device_class']
    }

    # Return our built discovery config
    return json.dumps(mqtt_data)


def publish_to_mqtt(reg_data, value, topic_prefix, host, device_name):
    json_send = config_json(reg_data, topic_prefix, host, device_name)

    if json_send is not None:
        client = paho.Client()
        client.username_pw_set(config.mqtt_user, config.mqtt_password)
        client.connect(config.mqtt_host, int(config.mqtt_port))
        if config.discovery_messages:
            client.publish("homeassistant/sensor/" + topic_prefix + "/" + host + "_" + reg_data['datapoint_key'] +
                           "/config", json_send, qos=0)

        client.publish(topic_prefix + "/" + host + "/" + reg_data['datapoint_key'], value, qos=1)
        client.disconnect()
    else:
        logging.warning(reg_data['datapoint_key'] + " not configured")


while True:
    total_read_succeed = True
    with open('profiles/' + config.device_profile, 'r') as f:
        registers_data = json.load(f)

    for item in registers_data['datapoints']:
        resp = requests.get(config.modbus_api_url + 'modbus?register=' + str(item['register']) +
                            'number=1&registerType=' + item['register_type'])
        data = literal_eval(resp.json()['data'])
        if resp.status_code == '200':
            publish_to_mqtt(reg_data=item, value=int(data[0]) * item['scale'],
                            topic_prefix=config.mqtt_topic_prefix,
                            host=config.mqtt_host_id,
                            device_name=config.mqtt_device_name)

        else:
            total_read_succeed = False

    if total_read_succeed:
        publish_to_mqtt(key="update", value=get_timestamp(), topic_prefix=config.mqtt_topic_prefix,
                        host=config.mqtt_host_id, device_name=config.mqtt_device_name)
        sleepTime = 10
    else:
        logging.warning('Failed to read from modbus, retry in 10sec')
        sleepTime = 10

    time.sleep(sleepTime)
