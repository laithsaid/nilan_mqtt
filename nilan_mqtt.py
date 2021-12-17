import argparse
import logging.handlers
import sys
import os
import time
import paho.mqtt.client as mqtt
from pymodbus.client.sync import ModbusSerialClient as ModbusClient

version = "0.1"
log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'nilan_mqtt.log')
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
    modbus_client = ModbusClient(method='rtu', port='/dev/ttyUSB0', stopbits=1, bytesize=8, parity='E', baudrate=19200)
    if function == 'input registers':
        val = modbus_client.read_input_registers(start_reg, nr_of_regs, unit=30)
    else:
        val = modbus_client.read_holding_registers(start_reg, nr_of_regs, unit=30)

    if not val.isError():
        return True, val.registers
    else:
        logging.warning("error: {}".format(val))
        return False, ''


def message_handler(mqtt_client, userdata, msg):
    logging.info('message_handler')
    try:
        (prefix, function, slaveid, functioncode, register) = msg.topic.split("/")
        if function != 'set':
            return
        if int(slaveid) not in range(0, 255):
            logging.warning("on message - invalid slaveid " + msg.topic)
            return

        if not (0 <= int(register) < sys.maxint):
            logging.warning("on message - invalid register " + msg.topic)
            return

    except Exception as e:
        logging.error("Error on message " + msg.topic + " :" + str(e))


def connect_handler(mqtt_client, userdata, flag, rc):
    logging.info('connect_handler')
    logging.info("Connected to MQTT broker with rc=%d" % rc)
    mqtt_client.subscribe(mqtt_topic + "set/+/+", qos=0)
    mqtt_client.publish(mqtt_topic + "connected", 2, qos=mqtt_qos, retain=mqtt_retain)


def disconnect_handler(mqtt_client, userdata, rc):
    logging.info('disconnect_handler')
    logging.warning("Disconnected from MQTT broker with rc=%d" % (rc))
    logging.info('mqtt_clientid: ' + mqtt_clientid)
    mqtt_client.connected_flag = False
    mqtt_client.disconnect_flag = True


def establish_mqtt_connection(mqtt_clientid, mqtt_host, mqtt_port, mqtt_keep_alive, mqtt_qos, mqtt_retain):
    logging.info('establish_mqtt_connection')
    try:
        # mqtt_clientid = mqtt_clientid + "-" + str(time.time())
        logging.info('mqtt_clientid: ' + mqtt_clientid)
        mqtt_client = mqtt.Client(client_id=mqtt_clientid)
        mqtt_client.on_connect = connect_handler
        mqtt_client.on_message = message_handler
        mqtt_client.on_disconnect = disconnect_handler
        mqtt_client.username_pw_set(username="homeassistant", password="eu4cif3aWaijechash1doh1thah1vohH4pon2ohz0eeFo2phah9dajaif0zai6ge")
        mqtt_client.will_set(mqtt_topic + "connected", 0, qos=mqtt_qos, retain=mqtt_retain)
        mqtt_client.disconnected = True
        mqtt_client.connect(mqtt_host, port=mqtt_port, keepalive=mqtt_keep_alive)
        mqtt_client.loop_start()
        return mqtt_client

    except Exception as e:
        logging.error("Unhandled error [" + str(e) + "]")
        sys.exit(1)


def publish_message(mqtt_client, topic, msg, mqtt_qos, mqtt_retain):
    mqtt_client.publish(topic, payload=msg, qos=mqtt_qos, retain=mqtt_retain)


parser = argparse.ArgumentParser(description='read data from ModBus and send it to MQTT broker')
# MQTT parameters
parser.add_argument('--mqtt-host', default='localhost', help='MQTT broker address. [localhost]')
parser.add_argument('--mqtt-port', default='1883', type=int, help='MQTT broker port. [1883]')
parser.add_argument('--mqtt-qos', default='0', type=int, help='MQTT quality of service. [0]')
parser.add_argument('--mqtt-retain', default='True', choices=['True', 'False'], help='MQTT retain. [True]')
parser.add_argument('--mqtt-topic', default='modbus/',
                    help='MQTT Topic used for subscribing/publishing. ["modbus/"]')
parser.add_argument('--mqtt-clientid', default='modbus_mqtt', help='Client ID for MQTT connection. [modbus_mqtt]')
parser.add_argument('--mqtt-keep-alive', default='360', type=int, help='Keep alive time for MQTT connection. [360]')

# program parameters
parser.add_argument('--log', default='INFO', choices=['CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG', 'NOTSET'],
                    help='logging level. Use DEBUG for maximum detail. [INFO]')

args = parser.parse_args()

# read config from input arguments
mqtt_host = args.mqtt_host
mqtt_port = args.mqtt_port
mqtt_qos = args.mqtt_qos
if args.mqtt_retain == 'true':
    mqtt_retain = True
elif args.mqtt_retain == 'false':
    mqtt_retain = False
else:
    logging.warning("Unknown MQTT retain. Should be true or false. Default true will be used.")
    mqtt_retain = True
mqtt_topic = args.mqtt_topic
mqtt_clientid = args.mqtt_clientid
mqtt_keep_alive = args.mqtt_keep_alive
log = args.log

logging.getLogger().setLevel(log)
logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

if not mqtt_topic.endswith("/"):
    mqtt_topic += "/"

logging.info('Starting modbus_mqtt V%s with topic prefix \"%s\"' % (version, mqtt_topic))

# signal.signal(signal.SIGINT, signal_handler)

# mqtt_client = MQTTClient(mqtt_host, mqtt_port, mqtt_qos, mqtt_retain, mqtt_topic, mqtt_clientid, mqtt_keep_alive)
mqtt_client = establish_mqtt_connection(mqtt_clientid, mqtt_host, mqtt_port, mqtt_keep_alive, mqtt_qos, mqtt_retain)
time.sleep(5)
mqtt_connect_payload = '{"name": "Nilan", "device_class": "None", "state_topic": "nilan/state", "unique_id": "nilan", "device": {"identifiers": "nilan","name": "nilan", "model": "Comfort 300LR", "manufacturer": "Nilan"}}'
publish_message(mqtt_client, 'nilan/', mqtt_connect_payload, mqtt_qos, mqtt_retain)

while True:
    total_read_succeed = True
    read_result = []
    read_succeed, value = read_registers(200, 22, 'input registers')
    if read_succeed:
        publish_message(mqtt_client, 'nilan/temperature/T0_Controller/', int(value[0]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/temperature/T3_Exhaust/', int(value[3]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/temperature/T4_Outlet/', int(value[4]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/temperature/T7_Inlet/', int(value[7]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/temperature/T8_Outdoor/', int(value[8]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/temperature/T15_Room/', int(value[15]) / 100, mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/humidity/RH/', int(value[21]) / 100, mqtt_qos, mqtt_retain)
    else:
        total_read_succeed = False

    read_succeed, value = read_registers(1000, 3, 'input registers')
    if read_succeed:
        publish_message(mqtt_client, 'nilan/state/Run_State/', run_act_mapping(value[0]), mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/state/Operation_Mode/', mode_act_mapping(value[1]), mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/state/Control_State/', state_mapping(value[2]), mqtt_qos, mqtt_retain)
    else:
        total_read_succeed = False

    read_succeed, value = read_registers(1204, 3, 'input registers')
    if read_succeed:
        publish_message(mqtt_client, 'nilan/efficiency/Passive_heat_exchanger_efficiency/', int(value[0]) / 100,
                        mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/capacity/Air_Temperature_Actual_Capacity/', int(value[2]) / 100, mqtt_qos,
                        mqtt_retain)
    else:
        total_read_succeed = False

    read_succeed, value = read_registers(200, 2, 'holding registers')
    if read_succeed:
        publish_message(mqtt_client, 'nilan/fan/Exhaust fan speed/', int(value[0]) / 100,
                        mqtt_qos, mqtt_retain)
        publish_message(mqtt_client, 'nilan/fan/Inlet fan speed/', int(value[1]) / 100, mqtt_qos,
                        mqtt_retain)
    else:
        total_read_succeed = False

    if total_read_succeed:
        sleepTime = 300
    else:
        logging.warning('Failed to read from modbus, retry in 10sec')
        sleepTime = 10

    time.sleep(sleepTime)
