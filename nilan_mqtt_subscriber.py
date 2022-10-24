import logging.handlers
from tzlocal import get_localzone
import json
import config
import os
import time
import random
from datetime import datetime
import paho.mqtt.client as paho
from pymodbus.client.sync import ModbusSerialClient as ModbusClient

version = "0.1"

log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), config.mqtt_host_id + '.log')
print(log_file)
logging.basicConfig(filename=log_file,
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.INFO)


def connect_mqtt() -> paho:
    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            print("Connected to MQTT Broker!")
        else:
            print("Failed to connect, return code %d\n", rc)

    client = paho.Client()
    client.username_pw_set(config.mqtt_user, config.mqtt_password)
    client.on_connect = on_connect
    client.connect(config.mqtt_host, int(config.mqtt_port))
    return client


def subscribe(client: paho):
    def on_message(client, userdata, msg):
        print(f"Received `{msg.payload.decode()}` from `{msg.topic}` topic")

    client.subscribe(config.mqtt_topic_prefix)
    client.on_message = on_message


def run():
    client = connect_mqtt()
    subscribe(client)
    client.loop_forever()


if __name__ == '__main__':
    run()
