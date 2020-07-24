import websockets
import json
import logging
import asyncio
import dpath.util

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


class HASSWebSocketController:
    ws = None
    event_rq_id = 1
    bulk_rq_id = 2
    data_sources = []

    def __init__(self, url, auth_token):
        self.url = url
        self.auth_token = auth_token

    def connect(self):
        # Create task
        asyncio.create_task(self.client_handler())

    async def client_handler(self):
        print(f"starting ws at url: {self.url}")
        async with websockets.connect(self.url) as websocket:
            self.ws = websocket
            # Wait for incoming message from server
            async for message in websocket:
                logging.debug(f"Received message: {message}")
                await self.on_message(websocket, message)

    async def on_message(self, ws, message):
        # Authentication with HASS Websockets
        message = json.loads(message)
        logging.debug(f"Message received: {message}")

        if 'type' in message and message['type'] == 'auth_required':
            logging.info("Authentication requested")
            auth_response = {'type': 'auth', 'access_token': self.auth_token}
            await ws.send(json.dumps(auth_response))

        elif 'type' in message and message['type'] == "auth_invalid":
            logging.error("Authentication failed")

        elif 'type' in message and message['type'] == "auth_ok":
            logging.info("Authentication successful")
            # Authentication successful
            # Send subscription command
            events_command = {
                "id": self.event_rq_id,
                "type": "subscribe_events",
                "event_type": "state_changed"
            }
            await ws.send(json.dumps(events_command))
            logging.info("Event update request sent")

            # Request full status update to get current value
            events_command = {
                "id": self.bulk_rq_id,
                "type": "get_states",
            }
            await ws.send(json.dumps(events_command))
            logging.info("All states request sent")

        elif 'type' in message and message['id'] == self.event_rq_id:
            # Look for state_changed events
            logging.info("Potential event update received")
            # Check for data
            if not keys_exist(message, 'event', 'data'):
                return
            # Notify attached data sources
            for ds in self.data_sources:
                ds.parse_potential_update(message['event']['data'])

        elif 'type' in message and message['id'] == self.bulk_rq_id:
            # Look for state_changed events
            logging.info("Bulk update received")
            if message.get('result') is None:
                return
            # Extract data
            bulk_update = message.get('result')
            # Loop through statuses
            for status in bulk_update:
                # Notify attached data sources
                for ds in self.data_sources:
                    ds.parse_potential_update(status)
        else:
            logging.debug(f"Unknown/unhandled message received: {message}")


if __name__ == "__main__":
    pass
