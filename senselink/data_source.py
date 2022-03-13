# Copyright 2022, Charles Powell

class DataSource:
    _power = None
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
        if self._power is not None:
            return self._power

        # Otherwise, determine wattage
        if self.state:
            # On
            power = self.min_watts + self.on_fraction * self.delta_watts
        else:
            # Off
            power = self.off_usage
        return power

    @power.setter
    def power(self, new_power):
        self._power = new_power

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


if __name__ == "__main__":
    pass
