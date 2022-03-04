# Copyright 2020, Charles Powell

import logging
import dpath.util
import asyncio
from math import isclose
from DataController import HASSController
from DataController import MQTTController, MQTTListener


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


def get_float_at_path(message, path, default_value=None):
    # Get attribute value, checking to force it to be a number
    raw_value = safekey(message, path)
    try:
        value = float(raw_value)
    except (ValueError, TypeError):
        logging.debug(f'Unable to convert attribute path {path} value ({raw_value}) to float, using {default_value}')
        value = default_value

    return value


class DataSource:
    _voltage = 120
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
            self.voltage = details.get('voltage') or 120

            self.delta_watts = self.max_watts - self.min_watts

    @property
    def power(self):
        # Build response
        # Determine wattage
        if self.state:
            # On
            power = self.min_watts + self.on_fraction * self.delta_watts
        else:
            # Off
            power = self.off_usage
        return power

    @property
    def current(self):
        # Determine current, assume 120V
        voltage = self.voltage
        current = self.power / voltage
        return current

    @property
    def voltage(self):
        # Return preset voltage
        return self._voltage

    @voltage.setter
    def voltage(self, new_voltage):
        self._voltage = new_voltage

    def add_controller(self, controller):
        # Provided to allow override
        self.controller = controller
        # Add self to passed-in controller (which might be None, for static plugs)
        if self.controller is not None:
            self.controller.data_sources.append(self)


class MutableSource(DataSource):
    _power = 0.0

    def __init__(self, identifier, details, controller=None):
        super().__init__(identifier, details, controller)
        if details is not None:
            self.power = details.get('power') or 0.0

    @property
    def power(self):
        return self._power

    @power.setter
    def power(self, new_power):
        self._power = new_power


class AggregateSource(DataSource):

    def __init__(self, identifier, details, controller):
        super().__init__(identifier, details, controller)

        self.elements = []

        if details is not None:
            self.element_ids = details.get('elements') or []

    @property
    def power(self):
        # Get power values from individual elements, and sum
        plug_powers = list(map(lambda plug: plug.power, self.elements))
        sum_power = sum(plug_powers)
        return sum_power


class HASSSource(DataSource):
    # Primary output property
    _power = 0.0

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


class MQTTSource(DataSource):
    # Primary output property
    _power = 0.0
    timer = None

    def add_controller(self, controller):
        # Add self to passed-in MQTT Data Controller
        if not isinstance(controller, MQTTController):
            raise TypeError(
                f"Incorrect controller type {type(self.controller).__name__} passed to MQTT Data Source")
        super().add_controller(controller)

    def __init__(self, identifier, details, controller):
        super().__init__(identifier, details, controller)

        if details is not None:
            # Min/max values for the wattage reference from the source (i.e. 0 to 255 brightness, 0 to 100%, etc)
            self.attribute_min = details.get('attribute_min') or 0.0
            self.attribute_max = details.get('attribute_max') or 0.0

            # MQTT Topics and handling
            self.power_topic = details.get('power_topic') or None
            self.power_topic_keypath = details.get('power_topic_keypath') or None
            self.state_topic = details.get('state_topic') or None
            self.state_topic_keypath = details.get('state_topic_keypath') or None
            self.on_state_value = details.get('on_state_value') or 'on'
            self.off_state_value = details.get('off_state_value') or 'off'
            self.attribute_topic = details.get('attribute_topic') or None
            self.attribute_topic_keypath = details.get('attribute_topic_keypath') or None
            self.timeout_duration = details.get('timeout_duration') or None

            if not any((self.attribute_topic, self.power_topic, self.state_topic)):
                # Need at least ONE topic
                raise AssertionError(
                    f"At least one topic (power, attribute, or state) must be provided to monitor!")

            if all((self.attribute_topic, self.power_topic)):
                # Defining attribute AND power topics doesn't make sense!
                raise AssertionError(
                    f"Power and Attribute topics cannot be set simultaneously!")

            self.attribute_delta = self.attribute_max - self.attribute_min

    async def timeout(self, timeout_value):
        # Sleep for specified time (seconds)
        await asyncio.sleep(timeout_value)
        # If we get here, set to off_usage
        logging.info(f'Update timeout reached for {self.identifier}, setting to off_usage')
        self.update_power(self.off_usage, timeout=False)
        self.state = False

    @property
    def power(self):
        return self._power

    def update_power(self, value, timeout=True):
        try:
            fval = float(value)
        except ValueError:
            logging.warning(f'Failed to convert power value ("{value}") for {self.identifier} to float, ignoring')
            return

        # Reset previous timer
        if self.timeout_duration is not None and timeout:
            if self.timer is not None:
                logging.debug(f'Cancelling prior MQTT timeout timer')
                self.timer.cancel()
            logging.debug(f'Created MQTT timer with duration {self.timeout_duration}')
            self.timer = asyncio.create_task(self.timeout(self.timeout_duration))

        if not isclose(fval, self.power):
            self._power = fval
            # Assume off if reported power usage is close to off_usage
            if isclose(self.power, self.off_usage):
                self.state = False
                logging.debug(f'Power equal to off_usage for {self.identifier}, assuming off')
            logging.debug(f'Power updated for {self.identifier}: {round(fval, 4)}')

    async def power_handler(self, value):
        logging.debug(f'Power topic update for {self.identifier}: {value}')
        self.update_power(value)

    async def state_handler(self, value):
        logging.debug(f'State topic update for {self.identifier}: {value}')
        # Act immediate if state is being set to off
        if value == self.off_state_value:
            # Device is off
            self.state = False
            self.update_power(self.off_usage)
            logging.debug(f'State set to OFF for {self.identifier}')
        elif value == self.on_state_value:
            # Device is on, but action depends on if a attribute topic is also defined,
            # to distinguish between a state+attribute plug or a state-only plug
            if self.attribute_topic is not None:
                # Update state only, do not assume wattage because it may be updated separately
                # Wattage will be whatever the most recent wattage value was!
                self.state = True
                logging.debug(f'State set to ON for {self.identifier}, wattage to be set by attribute')
            else:
                # Update state and set to max_wattage for a binary type plug
                self.state = True
                self.update_power(self.max_watts)
                logging.debug(f'State set to ON for {self.identifier}, using max_watts for power value')
        else:
            # State does not match on or off values, so check if it's a float
            try:
                fstate = float(value)
                if self.power_topic is None:
                    # No power topic defined, so use this numeric value as power
                    logging.debug(f'State update is numeric and no power_topic defined, using as power value')
                    self.update_power(fstate)
            except ValueError:
                logging.debug(f'State update ("{value}") is non-numeric and does not match on/off values, ignoring')

    async def attribute_handler(self, value):
        logging.debug(f'Attribute topic update for {self.identifier}: {value}')
        # Get attribute value and scale to provided values
        try:
            attribute_value = float(value)
        except ValueError:
            logging.warning(f'Non-float value ("{value}") received for attribute update, unable to update!')
            self._power = self.off_usage
            self.state = False
            return

        # Clamp to specified min/max
        clamp_attr = min(max(self.attribute_min, attribute_value), self.attribute_max)
        if attribute_value > clamp_attr or attribute_value < clamp_attr:
            logging.error(f"Attribute for {self.identifier} outside expected values")

        # Use linear scaling (for now)
        self.on_fraction = (clamp_attr - self.attribute_min) / self.attribute_delta
        scaled_power = self.min_watts + self.on_fraction * self.delta_watts
        self.update_power(scaled_power)
        logging.debug(f"Attribute {self.identifier} at fraction: {self.on_fraction}")

    def listeners(self) -> [MQTTListener]:
        # Return MQTTListener objects (topic and function)
        logging.info(f'Generating listeners for {self.identifier}')
        listeners = []
        if self.power_topic is not None:
            listeners.append(MQTTListener(self.power_topic, [self.power_handler]))
        if self.state_topic is not None:
            listeners.append(MQTTListener(self.state_topic, [self.state_handler]))
        if self.attribute_topic is not None:
            listeners.append(MQTTListener(self.attribute_topic, [self.attribute_handler]))

        return listeners
