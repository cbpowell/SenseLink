# Copyright 2020, Charles Powell

import random
import logging
from .data_source import DataSource

from typing import Type
from typing import Dict

# Generator for random MAC address
# Thanks to @pklaus: https://gist.github.com/pklaus/9638536


def random_bytes(num=6):
    return [random.randrange(256) for _ in range(num)]


def generate_mac(uaa=False, multicast=False, oui=None, separator=':', byte_fmt='%02x'):
    mac = random_bytes()
    if oui:
        if type(oui) == str:
            oui = [int(chunk, 16) for chunk in oui.split(separator)]
        mac = oui + random_bytes(num=6 - len(oui))
    else:
        if multicast:
            mac[0] |= 1  # set bit 0
        else:
            mac[0] &= ~1  # clear bit 0
        if uaa:
            mac[0] &= ~(1 << 1)  # clear bit 1
        else:
            mac[0] |= 1 << 1  # set bit 1
    return separator.join(byte_fmt % b for b in mac)


def generate_deviceid():
    deviceid_bytes = random_bytes(num=20)
    return ''.join('%02x' % b for b in deviceid_bytes)


class PlugInstance:
    start_time = None
    data_source = None
    in_aggregate = False  # Assume not in aggregate to start
    skip_rate = 0.0
    _response_counter = 0

    def __init__(self, identifier, alias=None, mac=None, device_id=None):
        self.identifier = identifier
        if mac is None:
            new_mac = generate_mac(oui='53:75:31')
            logging.info("Spoofed MAC: %s", new_mac)
            self.mac = new_mac
        else:
            self.mac = mac

        if device_id is None:
            new_device_id = generate_deviceid()
            logging.info("Spoofed Device ID: %s", new_device_id)
            self.device_id = new_device_id
        else:
            self.device_id = device_id

        if alias is None:
            self.alias = "Spoofed TP-Link Kasa HS110 " + self.device_id[0:8]
        else:
            self.alias = alias

    @classmethod
    # Convenience method to create a lot of plugs
    def configure_plugs(cls, plugs, data_source_class: Type[DataSource], data_controller=None) -> Dict:
        # Loop through all plugs
        instances = {}
        for plug in plugs:
            # Get specified identifier
            plug_id = next(iter(plug.keys()))
            # Get plug details
            details = plug.get(plug_id)
            if details is not None:
                # Define main details
                alias = details.get('alias')
                mac = details.get('mac')
                device_id = details.get('device_id')
                skip_rate = details.get('skip_rate') or 0.0

                # Create and configure instance
                instance = cls(plug_id, alias, mac, device_id)
                instance.skip_rate = skip_rate

                # Generate data source with details, and assign
                instance.data_source = data_source_class(plug_id, details, data_controller)

                # Check if this MAC has already been used
                if mac in instances.keys():
                    # Assertion error - can't use the same MAC twice!
                    prev_id = instances[mac]
                    raise AssertionError(
                        f"Configuration Error: Two plugs configured with the same MAC address! ({prev_id}, {plug_id})")

                # Add this plug to list of instances
                instances[mac] = instance

                logging.debug(f"Added plug: {plug_id}")

        return instances

    @property
    def power(self):
        return self.data_source.power

    def generate_response(self):
        # Grab latest values from source
        power = self.data_source.power
        current = self.data_source.current
        voltage = self.data_source.voltage

        # Response dict
        response = {
            "emeter": {
                "get_realtime": {
                    "current": current,
                    "voltage": voltage,
                    "power": power,
                    "total": 0,     # Unsure if this needs a value, appears not to
                    "err_code": 0   # No errors here!
                }
            },
            "system": {
                "get_sysinfo": {
                    "err_code": 0,
                    "sw_ver": "1.2.5 Build 171206 Rel.085954",
                    "hw_ver": "1.0",
                    "type": "IOT.SMARTPLUGSWITCH",
                    "model": "HS110(US)", # Previously used 'SenseLink', but first-run issues were found, see https://github.com/cbpowell/SenseLink/issues/17
                    "mac": self.mac.upper(),
                    "deviceId": self.mac.upper(),
                    "alias": self.alias,
                    "relay_state": 1,  # Assuming it's on, not sure it matters
                    "updating": 0
                }
            }
        }

        return response

    def should_respond(self, apply_counter=True):
        if self._response_counter < 1:
            if apply_counter:
                self._response_counter = self.skip_rate
            return True
        else:
            if apply_counter:
                # Decrement counter
                self._response_counter = max(self._response_counter - 1, 0)
            return False


if __name__ == "__main__":
    # Convenience function to generate a MAC address and Device ID
    gen_device_id = generate_deviceid()
    print(f"Generated Device ID:   {gen_device_id.upper()}")
    gen_mac = generate_mac(oui='50:c7:bf')
    print(f"Generated MAC:         {gen_mac.upper()}")
