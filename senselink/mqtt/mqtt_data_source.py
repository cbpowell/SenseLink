# Copyright 2022, Charles Powell
import logging
import asyncio
from math import isclose
from senselink.data_source import DataSource
from .mqtt_controller import MQTTController
from .mqtt_listener import MQTTListener


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
