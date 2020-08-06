import logging
import dpath.util
from DataController import HASSController


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


class DataSource:
    voltage = 120
    instances = []
    state = 1.0  # Assume on
    off_usage = 0.0
    min_watts = 0.0
    max_watts = 0.0
    on_fraction = 1.0

    def __init__(self, identifier, details, controller=None):
        self.identifier = identifier
        self.controller = controller
        if details is not None:
            min_watts = details.get('min_watts') or None
            self.off_usage = details.get('off_usage') or min_watts
            self.min_watts = min_watts or 0.0
            self.max_watts = details.get('max_watts')
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


class HASSSource(DataSource):
    # Primary output property
    power = 0.0

    def __init__(self, identifier, details, controller):
        super().__init__(identifier, details, controller)

        # Add self to passed-in Websocket controller
        if not isinstance(self.controller, HASSController):
            raise TypeError(f"Incorrect controller type {self.controller.__class__.__name__} passed to HASS Data Source")
        self.controller.data_sources.append(self)

        if details is not None:
            # Entity ID
            self.entity_id = details.get('entity_id')
            # Min/max values for the wattage reference from the source (i.e. 0 to 255 brightness, 0 to 100%, etc)
            self.attribute_min = details.get('attribute_min') or 0.0
            self.attribute_max = details.get('attribute_max')
            # Websocket response key paths
            # self.state_path = details.get('state_keypath') or None
            self.off_state_value = details.get('off_state_key') or 'off'
            self.attribute = details.get('attribute') or None
            self.attribute_path = details.get('attribute_keypath') or None

            if self.attribute is None and self.attribute_path is None:
                # Throw error, attribute is required
                raise Exception(f"Attribute or attribute path not defined for plug {identifier}")

            self.attribute_delta = self.attribute_max - self.attribute_min

    # Will be called by the controller for every incoming state update
    def parse_potential_update(self, message):
        # Check for entity_id of interest
        if safekey(message, 'entity_id') != self.entity_id:
            return

        # Determine type of state update (new or bulk)
        if 'new_state' in message:
            state_key = 'new_state/'
        elif 'state' in message:
            state_key = ''
        else:
            return

        # Get state, attribute of interest
        state_path = state_key + 'state'
        if self.attribute:
            attribute_path = state_key + 'attributes/' + self.attribute
        else:
            attribute_path = self.attribute_path

        state_value = safekey(message, state_path)
        attribute_value = safekey(message, attribute_path)

        if state_value is not None and state_value == self.off_state_value:
            # Device is off, set wattage appropriately
            self.power = self.off_usage
            self.state = 0
            logging.debug(f"Entity {self.entity_id} set to off")
        elif attribute_value is not None:
            # Get attribute value and scale to provided values
            # Clamp to specified min/max
            clamp_attr = min(max(self.attribute_min, attribute_value), self.attribute_max)
            if attribute_value > clamp_attr or attribute_value < clamp_attr:
                logging.info(f"Attribute for entity {self.entity_id} outside expected values")

            # Use linear scaling (for now)
            self.on_fraction = (clamp_attr - self.attribute_min) / self.attribute_delta
            self.power = self.min_watts + self.on_fraction * self.delta_watts
            logging.debug(f"Attribute {self.entity_id} at fraction: {self.on_fraction}")
        else:
            logging.info(f"Attribute update failure for {self.identifier}")
            logging.debug(f"No valid attribute or keypath found in update: {message}")
            return

        logging.info(f"Updated wattage for {self.identifier}: {self.get_power()}")

    def get_power(self):
        # Return internal value
        return self.power
