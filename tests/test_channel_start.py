import asyncio

from wecom.channel import WeComChannel
from wecom.config import WeComConfig


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
