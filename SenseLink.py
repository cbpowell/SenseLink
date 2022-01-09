# Copyright 2020, Charles Powell

import json
from time import time
import yaml
import argparse
from DataSource import *
from PlugInstance import *
from TPLinkEncryption import *
from aioudp import *

STATIC_KEY = 'static'
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


class SenseLink:
    _remote_ep = None
    _local_ep = None
    should_respond = True
    has_aggregate = False

    def __init__(self, config, port=9999):
        self.config = config
        self.port = port
        self.server_task = None
        self._instances = {}
        self._agg_instances = {}

    def create_instances(self):
        config = yaml.load(self.config, Loader=yaml.FullLoader)
        logging.debug(f"Configuration loaded: {config}")
        sources = config.get('sources')
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

            # HomeAssistant Plugs, using Websockets datasource
            elif source_id.lower() == HASS_KEY:
                # Configure this HASS Data source
                hass = source[HASS_KEY]
                if hass is None:
                    logging.error(f"Configuration error for Source {source_id}")
                url = hass['url']
                auth_token = hass['auth_token']
                ds_controller = HASSController(url, auth_token)

                # Generate plug instances
                plugs = hass[PLUGS_KEY]
                logging.info("Generating HASS instances")
                instances = PlugInstance.configure_plugs(plugs, HASSSource, ds_controller)
                self.add_instances(instances)

                # Start controller
                ds_controller.connect()

            # MQTT Plugs
            elif source_id.lower() == MQTT_KEY:
                # Configure this MQTT Data source
                mqtt = source[MQTT_KEY]
                if mqtt is None:
                    logging.error(f"Configuration error for Source {source_id}")
                host = mqtt['host']
                port = mqtt.get('port') or 1883
                username = mqtt.get('username') or None
                password = mqtt.get('password') or None
                mqtt_controller = MQTTController(host, port, username, password)

                # Generate plug instances
                plugs = mqtt[PLUGS_KEY]
                logging.info("Generating MQTT instances")
                instances = PlugInstance.configure_plugs(plugs, MQTTSource, mqtt_controller)
                self.add_instances(instances)

                # Start controller
                mqtt_controller.connect()

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

    def print_instance_wattages(self):
        for inst in self._instances:
            logging.info(f"Plug {inst.identifier} power: {inst.power}")

    async def start(self):
        self.create_instances()
        await self._serve()

    async def _serve(self):
        server_start = time()
        logging.info("Starting UDP server")
        self._local_ep = await open_local_endpoint('0.0.0.0', self.port)

        while True:
            data, addr = await self._local_ep.receive()
            request_addr = addr[0]
            decrypted_data = decrypt(data)

            try:
                json_data = json.loads(decrypted_data)
                # Sense requests the emeter and system parameters
                if keys_exist(json_data, "emeter", "get_realtime") and keys_exist(json_data, "system", "get_sysinfo"):
                    # Check for non-empty values, to prevent echo storms
                    if bool(safekey(json_data, 'emeter/get_realtime')):
                        # This is a self-echo, common with Docker without --net=Host!
                        logging.debug("Ignoring non-empty/non-Sense UDP request")
                        continue

                    logging.debug(f"Broadcast received from {request_addr}: {json_data}")

                    if self._remote_ep is None:
                        self._remote_ep = await open_remote_endpoint(request_addr, self.port)

                    # Build and send responses
                    for inst in self._instances.values():
                        # Check if this instance is in an aggregate
                        if inst.in_aggregate:
                            # Do not send individual response for this plug
                            logging.debug(f"Plug '{inst.identifier}' in aggregate, not sending discrete response")
                            continue

                        if inst.start_time is None:
                            inst.start_time = server_start
                        # Build response
                        response = inst.generate_response()
                        json_str = json.dumps(response, separators=(',', ':'))
                        encrypted_str = encrypt(json_str)
                        # Strip leading 4 bytes for...some reason
                        trun_str = encrypted_str[4:]

                        # Allow disabling response
                        if self.should_respond:
                            # Send response
                            logging.debug(f"Sending response: {response}")
                            self._remote_ep.send(trun_str)
                        else:
                            # Do not send response, but log for debugging
                            logging.debug(f"SENSE_RESPONSE disabled, response content: {response}")
                else:
                    logging.debug(f"Ignoring non-emeter JSON from {request_addr}: {json_data}")

            # Appears to not be JSON
            except ValueError:
                logging.debug("Did not receive valid JSON message, ignoring")
                continue


def main():
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="specify config file path")
    parser.add_argument("-l", "--log", help="specify log level (DEBUG, INFO, etc)")
    parser.add_argument("-q", "--quiet", help="do not respond to Sense UPD queries", action="store_true")
    args = parser.parse_args()
    config_path = args.config or '/etc/senselink/config.yml'
    loglevel = args.log or 'WARNING'

    loglevel = os.environ.get('LOGLEVEL', loglevel).upper()
    logging.basicConfig(level=loglevel)

    # Assume config file is in etc directory
    config_location = os.environ.get('CONFIG_LOCATION', config_path)
    logging.debug(f"Using config at: {config_location}")
    config = open(config_location, 'r')

    # Create controller, with config
    controller = SenseLink(config)
    if os.environ.get('SENSE_RESPONSE', 'True').upper() == 'TRUE' and not args.quiet:
        logging.info("Will respond to Sense broadcasts")
        controller.should_respond = True

    # Start and run indefinitely
    logging.info("Starting SenseLink controller")
    loop = asyncio.get_event_loop()
    tasks = asyncio.gather(*[controller.start()])
    loop.run_until_complete(tasks)


if __name__ == "__main__":
    main()
