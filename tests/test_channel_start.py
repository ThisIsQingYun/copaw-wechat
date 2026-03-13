import asyncio
import logging

from wecom.channel import WeComChannel
from wecom.config import WeComConfig
from wecom.models import InboundEnvelope
from wecom.ws.client import WeComWebSocketClient


class BlockingTransport:
    def __init__(self):
        self.sent = []
        self.closed = False
        self._release = asyncio.Event()

    async def send_json(self, payload):
        self.sent.append(payload)

    async def recv_json(self):
        await self._release.wait()
        return {
            'cmd': 'pong',
            'headers': {},
            'body': {},
        }

    async def close(self):
        self.closed = True
        self._release.set()


class StaticTransport:
    def __init__(self, payload):
        self.payload = payload

    async def send_json(self, payload):
        return None

    async def recv_json(self):
        return self.payload

    async def close(self):
        return None


def test_channel_start_launches_background_receive_loop_by_default():
    async def run_case():
        transport = BlockingTransport()
        config = WeComConfig.from_mapping(
            {
                'bot_id': 'bot_123',
                'secret': 'secret_456',
                'transport_factory': lambda: transport,
            }
        )
        channel = WeComChannel(process=None, config=config)
        channel._enqueue = lambda payload: None

        await channel.start()
        try:
            assert channel._receive_task is not None
            assert transport.sent[0]['cmd'] == 'aibot_subscribe'
        finally:
            await channel.stop()

    asyncio.run(run_case())


def test_channel_start_emits_diagnostic_logs(caplog):
    async def run_case():
        transport = BlockingTransport()
        config = WeComConfig.from_mapping(
            {
                'bot_id': 'bot_123',
                'secret': 'secret_456',
                'transport_factory': lambda: transport,
            }
        )
        channel = WeComChannel(process=None, config=config)
        channel._enqueue = lambda payload: None

        with caplog.at_level(logging.INFO):
            await channel.start()
        try:
            messages = [record.getMessage() for record in caplog.records]
            assert any('wecom channel starting' in message for message in messages)
            assert any('wecom websocket connected' in message for message in messages)
            assert any('wecom background receive loop started' in message for message in messages)
        finally:
            await channel.stop()

    asyncio.run(run_case())


def test_handle_envelope_ignores_heartbeat_frames(caplog):
    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        channel = WeComChannel(process=None, config=config)

        enqueued = []
        channel._enqueue = lambda payload: enqueued.append(payload)

        heartbeat = InboundEnvelope.from_dict(
            {
                'cmd': '',
                'headers': {'req_id': 'ping-123456'},
                'body': {},
            }
        )

        with caplog.at_level(logging.INFO):
            result = await channel._handle_envelope(heartbeat)

        messages = [record.getMessage() for record in caplog.records]
        assert result is None
        assert enqueued == []
        assert not any('wecom inbound envelope' in message for message in messages)

    asyncio.run(run_case())


def test_ws_client_heartbeat_frames_do_not_emit_info_logs(caplog):
    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        client = WeComWebSocketClient(config=config, transport_factory=lambda: None)
        client._transport = StaticTransport(
            {
                'cmd': '',
                'headers': {'req_id': 'ping-abcdef'},
                'body': {},
            }
        )

        with caplog.at_level(logging.INFO):
            envelope = await client.receive_one()

        messages = [record.getMessage() for record in caplog.records]
        assert envelope.is_heartbeat() is True
        assert not any('wecom websocket frame received' in message for message in messages)

    asyncio.run(run_case())
