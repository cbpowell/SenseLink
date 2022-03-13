# Copyright 2022, Charles Powell
from math import isclose

from senselink.data_source import DataSource
from .common import *
from .ha_controller import *

# Independently set WS logger
wslogger = logging.getLogger('websockets')
wslogger.setLevel(logging.WARNING)


class HASource(DataSource):
    # Primary output property
    _power = 0.0

    def add_controller(self, controller):
        # Add self to passed-in Websocket controller
        if not isinstance(controller, HAController):
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
            # Min/max values for the wattage reference from the source (i.e. 0 to 255 brightness, 0 to 100%, etc)
            self.attribute_min = details.get('attribute_min') or 0.0
            self.attribute_max = details.get('attribute_max') or 0.0
            # Websocket response key paths
            self.state_keypath = details.get('state_keypath') or 'state'
            self.off_state_value = details.get('off_state_value') or 'off'
            self.on_state_value = details.get('on_state_value') or None
            self.attribute = details.get('attribute') or None
            self.attribute_keypath = details.get('attribute_keypath') or None

            if self.attribute is None and self.power_keypath is None:
                # No specific key or keypath defined, assuming base state key provides power usage
                logging.debug(f"Defaulting to using base state value for power usage for {self.entity_id}")

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
        logging.debug(f"Parsing incremental update for {self.entity_id}: {message}")

        root_path = 'new_state/'
        self.parse_update(root_path, message)

    def parse_update(self, root_path, message):
        # State path
        state_path = root_path + self.state_keypath
        # Figure out attribute path
        if self.power_keypath is not None:
            # Get value at power keypath as attribute
            attribute_path = root_path + self.power_keypath
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
        attribute_value = get_float_at_path(message, attribute_path)

        # Try parsing values
        try:
            self.parse_update_values(state_value, attribute_value)
        except ValueError as err:
            logging.error(f'Error for entity {self.entity_id}: {err}, when parsing message: {message}')

    def parse_update_values(self, state_value, attribute_value):
        # Start with a None value for the resulting power
        parsed_power = None

        if state_value is not None:
            # Check if device is off as determined by state
            if state_value == self.off_state_value:
                # If user specifies a state value for OFF
                logging.debug(f"Entity {self.identifier} set to OFF based on state_value")
                # Device is off - set wattage appropriately
                parsed_power = self.off_usage
                self.state = False
                self.power = parsed_power
                logging.info(f"Updated wattage for {self.identifier}: {parsed_power}")
                # Do not continue execution, as attribute_value could still be populated
                # but this plug is defined to be OFF at this stage
                return

            # Check if device is on as determined by state (if on_state_value defined)
            if state_value == self.on_state_value:
                # If user specifies a state value for ON
                logging.debug(f"Entity {self.identifier} set to ON based on state_value")
                # Device is on - set power to max_wattage, but this may be overwritten
                # below if a valid attribute value is also found
                parsed_power = self.max_watts
                self.state = True

        # Try to get an attribute or power value
        if attribute_value is not None:
            if self.power_keypath is not None or self.attribute is None:
                if self.power_keypath is not None:
                    # If using power_keypath, just use value for power update
                    logging.debug(f'Pulling power from keypath: {self.power_keypath} for {self.identifier}')
                else:
                    logging.debug(f'Pulling power from base state value for {self.identifier}')

                parsed_power = attribute_value

                # Assume off if reported power usage is close to off_usage
                if isclose(self.power, self.off_usage):
                    self.state = False
            elif parsed_power is None:
                # A state-based power
                logging.debug(f'Determining power based on attribute for {self.identifier}')
                # Get attribute value and scale to provided values
                # Clamp to specified min/max
                clamp_attr = min(max(self.attribute_min, attribute_value), self.attribute_max)
                if attribute_value > clamp_attr or attribute_value < clamp_attr:
                    logging.error(f"Attribute for entity {self.entity_id} outside expected values")

                # Use linear scaling (for now)
                self.on_fraction = (clamp_attr - self.attribute_min) / self.attribute_delta
                parsed_power = self.min_watts + self.on_fraction * self.delta_watts
                logging.debug(f"Attribute {self.entity_id} at fraction: {self.on_fraction}")

        if parsed_power is None:
            logging.info(f"Attribute update failure for {self.identifier}")
            raise ValueError(f'No valid attribute found for {self.identifier}')

        self.power = parsed_power
        logging.info(f"Updated wattage for {self.identifier}: {parsed_power}")

    @property
    def power(self):
        return self._power

    @power.setter
    def power(self, new_power):
        self._power = new_power


if __name__ == "__main__":
    pass
