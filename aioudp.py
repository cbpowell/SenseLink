"""Provide high-level UDP endpoints for asyncio.

Example:

async def main():

    # Create a local UDP enpoint
    local = await open_local_endpoint('localhost', 8888)

    # Create a remote UDP enpoint, pointing to the first one
    remote = await open_remote_endpoint(*local.address)

    # The remote endpoint sends a datagram
    remote.send(b'Hey Hey, My My')

    # The local endpoint receives the datagram, along with the address
    data, address = await local.receive()

    # This prints: Got 'Hey Hey, My My' from 127.0.0.1 port 8888
    print(f"Got {data!r} from {address[0]} port {address[1]}")
"""

# From: https://gist.github.com/vxgmichel/e47bff34b68adb3cf6bd4845c4bed448

__all__ = ['open_local_endpoint', 'open_remote_endpoint']


# Imports

import asyncio
import warnings


# Datagram protocol

class DatagramEndpointProtocol(asyncio.DatagramProtocol):
    """Datagram protocol for the endpoint high-level interface."""

    def __init__(self, endpoint):
        self._endpoint = endpoint

    # Protocol methods

    def connection_made(self, transport):
        self._endpoint._transport = transport

    def connection_lost(self, exc):
        assert exc is None
        if self._endpoint._write_ready_future is not None:
            self._endpoint._write_ready_future.set_result(None)
        self._endpoint.close()

    # Datagram protocol methods

    def datagram_received(self, data, addr):
        self._endpoint.feed_datagram(data, addr)

    def error_received(self, exc):
        msg = 'Endpoint received an error: {!r}'
        warnings.warn(msg.format(exc))

    # Workflow control

    def pause_writing(self):
        assert self._endpoint._write_ready_future is None
        loop = self._endpoint._transport._loop
        self._endpoint._write_ready_future = loop.create_future()

    def resume_writing(self):
        assert self._endpoint._write_ready_future is not None
        self._endpoint._write_ready_future.set_result(None)
        self._endpoint._write_ready_future = None


# Enpoint classes

class Endpoint:
    """High-level interface for UDP enpoints.

    Can either be local or remote.
    It is initialized with an optional queue size for the incoming datagrams.
    """

    def __init__(self, queue_size=None):
        if queue_size is None:
            queue_size = 0
        self._queue = asyncio.Queue(queue_size)
        self._closed = False
        self._transport = None
        self._write_ready_future = None

    # Protocol callbacks

    def feed_datagram(self, data, addr):
        try:
            self._queue.put_nowait((data, addr))
        except asyncio.QueueFull:
            warnings.warn('Endpoint queue is full')

    def close(self):
        # Manage flag
        if self._closed:
            return
        self._closed = True
        # Wake up
        if self._queue.empty():
            self.feed_datagram(None, None)
        # Close transport
        if self._transport:
            self._transport.close()

    # User methods

    def send(self, data, addr):
        """Send a datagram to the given address."""
        if self._closed:
            raise IOError("Enpoint is closed")
        self._transport.sendto(data, addr)

    async def receive(self):
        """Wait for an incoming datagram and return it with
        the corresponding address.

        This method is a coroutine.
        """
        if self._queue.empty() and self._closed:
            raise IOError("Enpoint is closed")
        data, addr = await self._queue.get()
        if data is None:
            raise IOError("Enpoint is closed")
        return data, addr

    def abort(self):
        """Close the transport immediately."""
        if self._closed:
            raise IOError("Enpoint is closed")
        self._transport.abort()
        self.close()

    async def drain(self):
        """Drain the transport buffer below the low-water mark."""
        if self._write_ready_future is not None:
            await self._write_ready_future

    # Properties

    @property
    def address(self):
        """The endpoint address as a (host, port) tuple."""
        return self._transport.get_extra_info("socket").getsockname()

    @property
    def closed(self):
        """Indicates whether the endpoint is closed or not."""
        return self._closed


class LocalEndpoint(Endpoint):
    """High-level interface for UDP local enpoints.

    It is initialized with an optional queue size for the incoming datagrams.
    """
    pass


class RemoteEndpoint(Endpoint):
    """High-level interface for UDP remote enpoints.

    It is initialized with an optional queue size for the incoming datagrams.
    """

    def send(self, data):
        """Send a datagram to the remote host."""
        super().send(data, None)

    async def receive(self):
        """ Wait for an incoming datagram from the remote host.

        This method is a coroutine.
        """
        data, addr = await super().receive()
        return data


# High-level coroutines

async def open_datagram_endpoint(
        host, port, *, endpoint_factory=Endpoint, remote=False, **kwargs):
    """Open and return a datagram endpoint.

    The default endpoint factory is the Endpoint class.
    The endpoint can be made local or remote using the remote argument.
    Extra keyword arguments are forwarded to `loop.create_datagram_endpoint`.
    """
    loop = asyncio.get_event_loop()
    endpoint = endpoint_factory()
    kwargs['remote_addr' if remote else 'local_addr'] = host, port
    kwargs['protocol_factory'] = lambda: DatagramEndpointProtocol(endpoint)
    await loop.create_datagram_endpoint(**kwargs)
    return endpoint


async def open_local_endpoint(
        host='0.0.0.0', port=0, *, queue_size=None, **kwargs):
    """Open and return a local datagram endpoint.

    An optional queue size arguement can be provided.
    Extra keyword arguments are forwarded to `loop.create_datagram_endpoint`.
    """
    return await open_datagram_endpoint(
        host, port, remote=False,
        endpoint_factory=lambda: LocalEndpoint(queue_size),
        **kwargs)


async def open_remote_endpoint(
        host, port, *, queue_size=None, **kwargs):
    """Open and return a remote datagram endpoint.

    An optional queue size arguement can be provided.
    Extra keyword arguments are forwarded to `loop.create_datagram_endpoint`.
    """
    return await open_datagram_endpoint(
        host, port, remote=True,
        endpoint_factory=lambda: RemoteEndpoint(queue_size),
        **kwargs)


# Testing

try:
    import pytest
    pytestmark = pytest.mark.asyncio
except ImportError:  # pragma: no cover
    pass


async def test_standard_behavior():
    local = await open_local_endpoint()
    remote = await open_remote_endpoint(*local.address)

    remote.send(b'Hey Hey')
    data, address = await local.receive()

    assert data == b'Hey Hey'
    assert address == remote.address

    local.send(b'My My', address)
    data = await remote.receive()
    assert data == b'My My'

    local.abort()
    assert local.closed

    with pytest.warns(UserWarning):
        await asyncio.sleep(1e-3)
        remote.send(b'U there?')
        await asyncio.sleep(1e-3)

    remote.abort()
    assert remote.closed


async def test_closed_endpoint():
    local = await open_local_endpoint()
    future = asyncio.ensure_future(local.receive())
    local.abort()
    assert local.closed

    with pytest.raises(IOError):
        await future

    with pytest.raises(IOError):
        await local.receive()

    with pytest.raises(IOError):
        await local.send(b'test', ('localhost', 8888))

    with pytest.raises(IOError):
        local.abort()


async def test_queue_size():
    local = await open_local_endpoint(queue_size=1)
    remote = await open_remote_endpoint(*local.address)

    remote.send(b'1')
    remote.send(b'2')
    with pytest.warns(UserWarning):
        await asyncio.sleep(1e-3)
        assert await local.receive() == (b'1', remote.address)
    remote.send(b'3')
    assert await local.receive() == (b'3', remote.address)

    remote.send(b'4')
    await asyncio.sleep(1e-3)
    local.abort()
    assert local.closed
    assert await local.receive() == (b'4', remote.address)

    remote.abort()
    assert remote.closed


async def test_flow_control():
    m = n = 1024
    remote = await open_remote_endpoint("8.8.8.8", 12345)

    for _ in range(m):
        remote.send(b"a" * n)

    await remote.drain()

    for _ in range(m):
        remote.send(b"a" * n)

    remote.abort()
    await remote.drain()


if __name__ == '__main__':  # pragma: no cover
    pytest.main([__file__])