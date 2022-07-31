from flask import Flask, request
from flask_restful import Resource, Api, reqparse
import config
import os
import logging.handlers
from pymodbus.client.sync import ModbusSerialClient as ModbusClient

version = "0.1"
log_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), config.mqtt_host_id + '.log')
print(log_file)
logging.basicConfig(filename=log_file,
                    filemode='a',
                    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                    datefmt='%H:%M:%S',
                    level=logging.INFO)

app = Flask(__name__)
api = Api(app)


def read_registers(start_reg, nr_of_regs, function):
    try:
        start_reg = int(start_reg)
        nr_of_regs = int(nr_of_regs)

        modbus_client = ModbusClient(
            method='rtu',
            port=config.modbus_port,  # serial port
            stopbits=1,  # The number of stop bits to use
            bytesize=8,  # The bytesize of the serial messages
            parity=config.parity,  # Which kind of parity to use
            baudrate=19200  # The baud rate to use for the serial device
        )

        if function == 'input':
            val = modbus_client.read_input_registers(start_reg, nr_of_regs, unit=30)
        else:
            val = modbus_client.read_holding_registers(start_reg, nr_of_regs, unit=30)

        if not val.isError():
            return True, val.registers
        else:
            logging.warning("error: {}".format(val))
            return False, ''

    except Exception as exp:
        logging.error(f"error: {exp}")
        return False, ''


def write_register(register, value):
    try:
        register = int(register)
        value = int(value)

        modbus_client = ModbusClient(
            method='rtu',
            port=config.modbus_port,  # serial port
            stopbits=1,  # The number of stop bits to use
            bytesize=8,  # The bytesize of the serial messages
            parity=config.parity,  # Which kind of parity to use
            baudrate=19200  # The baud rate to use for the serial device
        )

        modbus_client.write_registers(register, [value], unit=30)
        val = modbus_client.read_holding_registers(register, 1, unit=30)

        if not val.isError():
            return True, val.registers
        else:
            logging.warning("error: {}".format(val))
            return False, ''

    except Exception as exp:
        logging.error(f"error: {exp}")
        return False, ''


class ModbusClient(Resource):
    def get(self):
        arguments = {'register': request.args.getlist('register')[0], 'number': int(request.args.getlist('number')[0]),
                     'registerType': request.args.getlist('registerType')[0]}

        if not arguments['registerType'] in {'input', 'holding'}:
            return {
                       'message': f"Register type {arguments['registerType']} is not supported."
                   }, 400
        elif arguments['number'] > 30:
            return {
                       'message': f"Not allowed to read more that 30 registers in one operation."
                   }, 400
        else:
            read_succeed, value = read_registers(arguments['register'], arguments['number'], arguments['registerType'])

        if read_succeed:
            return {'data': f"{value}"}, 200
        else:
            return {'message': f"Modbus read operation failed. Check log file."}, 200

    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('register')
        parser.add_argument('value')

        args = parser.parse_args()

        read_succeed, value = write_register(args['register'], args['value'])

        if read_succeed:
            return {'data': f"{value}"}, 200
        else:
            return {'message': f"Modbus write operation failed. Check log file."}, 200


api.add_resource(ModbusClient, '/modbus')

if __name__ == '__main__':
    app.run()
    # app.run(host='192.168.1.2', port=3000)
