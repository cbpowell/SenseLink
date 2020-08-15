# Copyright 2020, Charles Powell

import logging
import dpath.util
from math import isclose
from DataController import HASSController


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


def get_attribute_at_path(message, path):
    # Get attribute value, checking to force it to be a number
    raw_value = safekey(message, path)
    try:
        value = float(raw_value)
    except (ValueError, TypeError):
        logging.error(f'Unable to convert attribute path {path} value ({raw_value}) to float, using 0.0')
        value = 0.0

    return value


class DataSource:
    voltage = 120
    instances = []
    state = True  # Assume on
    off_usage = 0.0
    min_watts = 0.0
    max_watts = 0.0
    on_fraction = 1.0
    controller = None

    def __init__(self, identifier, details, controller=None):
        self.identifier = identifier
        self.add_controller(controller)
        if details is not None:
            min_watts = details.get('min_watts') or 0.0
            self.off_usage = details.get('off_usage') or min_watts
            self.min_watts = min_watts or 0.0
            self.max_watts = details.get('max_watts') or 0.0
            self.on_fraction = details.get('on_fraction') or 1.0

            self.delta_watts = self.max_watts - self.min_watts

    def get_power(self):
        # Build response
        # Determine wattage
        if self.state:
            # On
            power = self.min_watts + self.on_fraction * self.delta_watts
        else:
            # Off
            power = self.off_usage
        return power

    def get_current(self):
        # Determine current, assume 120V
        voltage = 120.0
        current = self.get_power() / voltage
        return current

    def add_controller(self, controller):
        # Provided to allow override
        self.controller = controller
        # Add self to passed-in controller (which might be None, for static plugs)
        if self.controller is not None:
            self.controller.data_sources.append(self)


class HASSSource(DataSource):
    # Primary output property
    power = 0.0

    def add_controller(self, controller):
        # Add self to passed-in Websocket controller
        if not isinstance(controller, HASSController):
            raise TypeError(
                f"Incorrect controller type {type(self.controller).__name__} passed to HASS Data Source")
        super().add_controller(controller)

    def __init__(self, identifier, details, controller):
        super().__init__(identifier, details, controller)

        if details is not None:
            # Entity ID
            self.entity_id = details.get('entity_id')
            # First check if power_keypath is defined, indicating this entity should provide a pre-calculated
            # power value, so no attribute scaling required
            self.power_keypath = details.get('power_keypath') or None
            if self.power_keypath is not None:
                # No other details required
                return
            # Min/max values for the wattage reference from the source (i.e. 0 to 255 brightness, 0 to 100%, etc)
            self.attribute_min = details.get('attribute_min') or 0.0
            self.attribute_max = details.get('attribute_max')
            # Websocket response key paths
            self.state_path = details.get('state_keypath') or 'state'
            self.off_state_value = details.get('off_state_value') or 'off'
            self.attribute = details.get('attribute') or None
            self.attribute_keypath = details.get('attribute_keypath') or None

            if self.attribute is None and self.power_keypath is None:
                # No specific key or keypath defined, assuming base state key provides power usage
                logging.debug(f"Defaulting to using base state value for power usage")

            self.attribute_delta = self.attribute_max - self.attribute_min

    def parse_bulk_update(self, message):
        # Check for entity_id of interest
        if safekey(message, 'entity_id') != self.entity_id:
            return
        logging.debug(f"Entity update received: {message}")

        root_path = ''
        self.parse_update(root_path, message)

    def parse_incremental_update(self, message):
        # Check for entity_id of interest
        if safekey(message, 'entity_id') != self.entity_id:
            return
        logging.debug(f"Parsing incremental update: {message}")

        root_path = 'new_state/'
        self.parse_update(root_path, message)

    def parse_update(self, root_path, message):
        # State path
        state_path = root_path + self.state_path
        # Figure out attribute path
        if self.power_keypath is not None:
            # Get value at power keypath as attribute
            attribute_path = self.power_keypath
        elif self.attribute is not None:
            # Get (single key) attribute
            attribute_path = root_path + 'attributes/' + self.attribute
        elif self.attribute_keypath is not None:
            # Get attribute at path specified
            attribute_path = root_path + self.attribute_keypath
        else:
            # Get the base state as the attribute (i.e. if power is reported directly as state)
            attribute_path = state_path

        # Pull values at determined paths
        state_value = safekey(message, state_path)
        attribute_value = get_attribute_at_path(message, attribute_path)

        # Try parsing values
        try:
            self.parse_update_values(state_value, attribute_value)
        except ValueError as err:
            logging.error(f'Error for entity {self.entity_id}: {err}, when parsing message: {message}')

    def parse_update_values(self, state_value, attribute_value):
        if attribute_value is not None and (self.power_keypath is not None or self.attribute is None):
            if self.power_keypath is not None:
                # If using power_keypath, just use value for power update
                logging.debug(f'Pulling power from keypath: {self.power_keypath} for {self.identifier}')
            else:
                logging.debug(f'Pulling power from base state value for {self.identifier}')

            self.power = attribute_value

            # Assume off if reported power usage is 0.0
            if isclose(self.power, 0.0):
                self.state = False
        elif state_value is not None and state_value == self.off_state_value:
            # If user specifies a state value
            logging.debug(f"Entity {self.entity_id} set to off")
            # Device is off, set wattage appropriately
            self.power = self.off_usage
            self.state = False
        elif attribute_value is not None:
            logging.debug(f'Pulling power from attribute for {self.identifier}')
            # Get attribute value and scale to provided values
            # Clamp to specified min/max
            clamp_attr = min(max(self.attribute_min, attribute_value), self.attribute_max)
            if attribute_value > clamp_attr or attribute_value < clamp_attr:
                logging.error(f"Attribute for entity {self.entity_id} outside expected values")

            # Use linear scaling (for now)
            self.on_fraction = (clamp_attr - self.attribute_min) / self.attribute_delta
            self.power = self.min_watts + self.on_fraction * self.delta_watts
            logging.debug(f"Attribute {self.entity_id} at fraction: {self.on_fraction}")
        else:
            logging.info(f"Attribute update failure for {self.identifier}")
            raise ValueError(f'No valid attribute found for {self.identifier}')

        logging.info(f"Updated wattage for {self.identifier}: {self.get_power()}")

    def get_power(self):
        # Return internal value
        return self.power
