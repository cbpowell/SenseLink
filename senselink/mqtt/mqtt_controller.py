# Copyright 2022, Charles Powell

import logging
import asyncio
from aiomqtt import Client, MqttError
from typing import Dict

from .mqtt_listener import MQTTListener

MQTT_LOGGER = logging.getLogger('mqtt')
MQTT_LOGGER.setLevel(logging.WARNING)


class MQTTController:
    client = None
    topics: Dict[str, MQTTListener] = None

    def __init__(self, host, port=1883, username=None, password=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password

        self.data_sources = []
        self.listeners = {}

    async def connect(self):
        # Create task
        await self.client_handler()

    async def client_handler(self):
        logging.info(f"Starting MQTT client to URL: {self.host}")
        reconnect_interval = 5  # [seconds]

        client = Client(self.host, self.port, username=self.username, password=self.password)
        while True:
            try:
                async with client:
                    await self.listen(client)
            except MqttError as error:
                logging.error(f'Disconnected from MQTT broker with error: {error}')
                logging.debug(f'MQTT client disconnected/ended, reconnecting in {reconnect_interval}...')
                await asyncio.sleep(reconnect_interval)
            except (KeyboardInterrupt, asyncio.CancelledError):
                return False
            except Exception as error:
                logging.error(f'Stopping MQTT client with error: {error}')
                return False

    async def listen(self, client):
        logging.info(f'MQTT client connected')
        # Add tasks for each data source handler
        for ds in self.data_sources:
            # Get handlers from data source
            ds_listeners = ds.listeners()
            # Iterate through data source listeners and convert to
            # 'prime' listeners for each topic
            for listener in ds_listeners:
                topic = listener.topic
                funcs = listener.handlers
                if topic in self.listeners:
                    # Add these handlers to existing top level topic handler
                    logging.debug(f'Adding handlers for existing prime Listener: {topic}')
                    ext_topic = self.listeners[topic]
                    ext_topic.handlers.extend(funcs)
                else:
                    # Add this instance as a new top level handler
                    logging.debug(f'Creating new prime Listener for topic: {topic}')
                    self.listeners[topic] = MQTTListener(topic, funcs)

        async with client.messages() as messages:
            # Subscribe to specified topics
            for topic, handlers in self.listeners.items():
                await client.subscribe(topic)
            # Handle messages that come in
            async for message in messages:
                topic = message.topic.value
                handlers = self.listeners[topic].handlers
                logging.debug(f'Got message for topic: {topic}')
                for func in handlers:
                    # Decode to UTF-8
                    payload = message.payload.decode()
                    await func(payload)


if __name__ == "__main__":
    pass
