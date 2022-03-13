# Copyright 2020, Charles Powell

import yaml
import asyncio
import argparse
import logging
import dpath.util
import json

from .data_source import *
from .plug_instance import *
from .tplink_encryption import *

from senselink.mqtt import *
from senselink.homeassistant import *

STATIC_KEY = 'static'
MUTABLE_KEY = 'mutable'
HASS_KEY = 'hass'
MQTT_KEY = 'mqtt'
AGG_KEY = 'aggregate'
PLUGS_KEY = 'plugs'


# Check if a multi-layer key exists
def keys_exist(element, *keys):
    if not isinstance(element, dict):
        raise AttributeError('keys_exists() expects dict as first argument.')
    if len(keys) == 0:
        raise AttributeError('keys_exists() expects at least two arguments, one given.')

    _element = element
    for key in keys:
        try:
            _element = _element[key]
        except KeyError:
            return False
    return True


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


class SenseLinkProtocol(asyncio.DatagramProtocol):
    transport = None
    target = None

    def __init__(self, instances, finished):
        self._instances = instances
        self.should_respond = True
        self.finished = finished

    def connection_made(self, transport):
        self.transport = transport

    def connection_lost(self, exc):
        pass

    def datagram_received(self, data, addr):
        # Decrypt request data
        decrypted_data = decrypt(data)
        # Determine target
        request_addr = self.target or addr[0]

        try:
            # Get JSON data
            json_data = json.loads(decrypted_data)

            # Sense requests the emeter and system parameters
            if keys_exist(json_data, "emeter", "get_realtime") and keys_exist(json_data, "system", "get_sysinfo"):
                # Check for non-empty values, to prevent echo storms
                if bool(safekey(json_data, 'emeter/get_realtime')):
                    # This is a self-echo, common with Docker without --net=Host!
                    logging.debug("Ignoring non-empty/non-Sense UDP request")
                    return

                logging.debug(f"Broadcast received from {request_addr}: {json_data}")

                # Build and send responses
                for inst in self._instances.values():
                    # Check if this instance is in an aggregate
                    if inst.in_aggregate:
                        # Do not send individual response for this plug
                        logging.debug(f"Plug '{inst.identifier}' in aggregate, not sending discrete response")
                        continue

                    # Build response
                    response = inst.generate_response()
                    json_str = json.dumps(response, separators=(',', ':'))
                    encrypted_str = encrypt(json_str)
                    # Strip leading 4 bytes for...some reason
                    trun_str = encrypted_str[4:]

                    # Allow disabling response, and rate limiting
                    plug_respond = inst.should_respond()
                    if self.should_respond and plug_respond:
                        # Send response
                        logging.debug(f"Sending response for plug {inst.identifier}: {response}")
                        self.transport.sendto(trun_str, addr)
                    elif not plug_respond:
                        logging.debug(f'Plug {inst.identifier} response rate limited')
                    else:
                        # Do not send response, but log for debugging
                        logging.debug(
                            f"SENSE_RESPONSE disabled, plug {inst.identifier} response content would be: {response}")
            else:
                logging.debug(f"Ignoring non-emeter JSON from {request_addr}: {json_data}")

        # Appears to not be JSON
        except ValueError:
            logging.debug("Did not receive valid JSON message, ignoring")


class SenseLink:
    transport = None
    protocol = None
    should_respond = True
    has_aggregate = False

    def __init__(self, config, port=9999):
        self.config = config
        self.port = port
        self.target = None
        self.server_task = None
        self._instances = {}
        self._agg_instances = {}
        self.tasks = set()

    def create_instances(self):
        config = yaml.load(self.config, Loader=yaml.FullLoader)
        logging.debug(f"Configuration loaded: {config}")
        sources = config.get('sources')
        self.target = config.get('target') or None
        aggregate = None

        for source in sources:
            # Get specified identifier
            source_id = next(iter(source.keys()))
            logging.debug(f"Adding {source_id} configuration")
            # Static value plugs
            if source_id.lower() == STATIC_KEY:
                # Static sources require no extra config
                static = source[STATIC_KEY]
                if static is None:
                    logging.error(f"Configuration error for Source {source_id}")
                # Generate plug instances
                plugs = static[PLUGS_KEY]
                logging.info("Generating Static instances")
                instances = PlugInstance.configure_plugs(plugs, DataSource)
                self.add_instances(instances)

            # Mutable value plugs
            elif source_id.lower() == MUTABLE_KEY:
                mutable = source[MUTABLE_KEY]
                if mutable is None:
                    logging.error(f"Configuration error for Source {source_id}")
                # Generate plug instances
                plugs = mutable[PLUGS_KEY]
                logging.info("Generating Mutable instances")
                instances = PlugInstance.configure_plugs(plugs, MutableSource)
                self.add_instances(instances)

            # HomeAssistant Plugs, using Websockets datasource
            elif source_id.lower() == HASS_KEY:
                # Configure this HASS Data source
                hass = source[HASS_KEY]
                if hass is None:
                    logging.error(f"Configuration error for Source {source_id}")
                url = hass['url']
                auth_token = hass['auth_token']
                hass_controller = HAController(url, auth_token)

                # Generate plug instances
                plugs = hass[PLUGS_KEY]
                logging.info("Generating HASS instances")
                instances = PlugInstance.configure_plugs(plugs, HASource, hass_controller)
                self.add_instances(instances)

                # Start controller
                hass_task = hass_controller.connect()
                self.tasks.add(hass_task)

            # MQTT Plugs
            elif source_id.lower() == MQTT_KEY:
                # Configure this MQTT Data source
                mqtt_conf = source[MQTT_KEY]
                if mqtt_conf is None:
                    logging.error(f"Configuration error for Source {source_id}")
                host = mqtt_conf['host']
                port = mqtt_conf.get('port') or 1883
                username = mqtt_conf.get('username') or None
                password = mqtt_conf.get('password') or None
                mqtt_controller = MQTTController(host, port, username, password)

                # Generate plug instances
                plugs = mqtt_conf[PLUGS_KEY]
                logging.info("Generating MQTT instances")
                instances = PlugInstance.configure_plugs(plugs, MQTTSource, mqtt_controller)
                self.add_instances(instances)

                # Start controller
                mqtt_task = mqtt_controller.connect()
                self.tasks.add(mqtt_task)

            # Aggregate-type Plugs
            elif source_id.lower() == AGG_KEY:
                # Only one aggregate key allowed
                if self.has_aggregate:
                    # Already defined, ignore this one
                    logging.warning(
                        f"""Multiple 'aggregate' groups defined - only one group is allowed. Ignoring this"""
                        """and all subsequent!""")
                    continue
                self.has_aggregate = True
                aggregate = source[AGG_KEY]
            else:
                logging.error(f"Source type '{source_id}' not recognized")

        if aggregate is not None:
            # Handle aggregate plugs, now that all instances are defined
            # Generate plug instances
            plugs = aggregate[PLUGS_KEY]
            logging.info("Generating Aggregate instances")
            instances = PlugInstance.configure_plugs(plugs, AggregateSource)
            for inst in instances.values():
                # Grab data source for this instance
                ag_ds = inst.data_source
                # So that we can get the element IDs (i.e. plug_id's)
                element_ids = ag_ds.element_ids
                # Use those element_ids to get actual instances from global instance dict
                elements = []
                for plug in self._instances.values():
                    if plug.identifier in element_ids:
                        # Check if this plug is already in another aggregate
                        if plug.in_aggregate:
                            logging.warning(f"""Configuration adds plug {plug.identifier} to more than one Aggregate"""
                                            f""" plug. Usage in Aggregate {inst.identifier} will be ignored.""")
                            continue
                        # We want this plug
                        elements.append(plug)
                        plug.in_aggregate = True
                # Pass these elements (top-level plugs) back to Aggregate data source
                ag_ds.elements = elements
            # Add these aggregate plugs to the instance list
            self.add_instances(instances)

    def add_instances(self, instances):
        # Check for duplicated MAC
        union_macs = [val for val in instances.keys() if val in self._instances.keys()]
        if any(union_macs):
            # Assertion error - can't use the same MAC twice!
            raise AssertionError(
                f"Configuration Error: Two plugs configured with the same MAC address! ({union_macs})")

        # Add to global instances
        self._instances = {**self._instances, **instances}

    def plug_for_mac(self, mac):
        return self._instances[mac]

    def print_instance_wattages(self):
        for inst in self._instances:
            logging.info(f"Plug {inst.identifier} power: {inst.power}")

    async def start(self):
        self.tasks.add(self.server_start())
        await asyncio.gather(*self.tasks)

    async def server_start(self):
        loop = asyncio.get_running_loop()
        finished = loop.create_future()
        protocol = SenseLinkProtocol(self._instances, finished)
        protocol.should_respond = self.should_respond
        protocol.target = self.target

        logging.info("Starting UDP server")
        try:
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: protocol,
                local_addr=('0.0.0.0', self.port))
        except Exception as err:
            logging.error(f'Error creating endpoint {err}')

        try:
            await finished
        except KeyboardInterrupt:
            logging.info('Interrupt received, stopping server')
            finished.set_result(True)
        finally:
            self.transport.close()


if __name__ == '__main__':
    pass
