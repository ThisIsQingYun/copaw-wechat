import asyncio
import logging

from wecom.channel import WeComChannel
from wecom.config import WeComConfig


def test_send_warns_when_no_delivery_path(caplog):
    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        channel = WeComChannel(process=None, config=config)

        with caplog.at_level(logging.WARNING):
            command = await channel.send('chat_1', 'hello', {'req_id': 'req_1'})

        messages = [record.getMessage() for record in caplog.records]
        assert command['cmd'] == 'aibot_respond_msg'
        assert any('wecom outbound command not sent' in message for message in messages)

    asyncio.run(run_case())


def test_send_uses_response_url_when_websocket_is_missing():
    async def run_case():
        post_calls = []

        async def fake_post(response_url, payload, timeout_seconds):
            post_calls.append((response_url, payload, timeout_seconds))
            return {'errcode': 0}

        config = WeComConfig.from_mapping(
            {
                'bot_id': 'bot_123',
                'secret': 'secret_456',
                'response_post_func': fake_post,
            }
        )
        channel = WeComChannel(process=None, config=config)

        response = await channel.send(
            'chat_1',
            'hello',
            {
                'req_id': 'req_1',
                'response_url': 'https://example.com/response',
            },
        )

        assert response == {'errcode': 0}
        assert post_calls == [
            (
                'https://example.com/response',
                {
                    'msgtype': 'markdown',
                    'markdown': {'content': 'hello'},
                },
                10,
            )
        ]

    asyncio.run(run_case())


def test_send_prefers_websocket_for_reply_mode_before_response_url():
    class FakeWsClient:
        def __init__(self):
            self.commands = []

        async def send_command(self, command):
            self.commands.append(command)

    async def run_case():
        post_calls = []

        async def fake_post(response_url, payload, timeout_seconds):
            post_calls.append((response_url, payload, timeout_seconds))
            return {'errcode': 0}

        config = WeComConfig.from_mapping(
            {
                'bot_id': 'bot_123',
                'secret': 'secret_456',
                'response_post_func': fake_post,
            }
        )
        channel = WeComChannel(process=None, config=config)
        channel._ws_client = FakeWsClient()

        command = await channel.send(
            'chat_1',
            'hello',
            {
                'req_id': 'req_1',
                'response_url': 'https://example.com/response',
            },
        )

        assert command['cmd'] == 'aibot_respond_msg'
        assert channel._ws_client.commands[0]['cmd'] == 'aibot_respond_msg'
        assert post_calls == []

    asyncio.run(run_case())


def test_send_logs_stream_payload_details(caplog):
    class FakeWsClient:
        def __init__(self):
            self.commands = []

        async def send_command(self, command):
            self.commands.append(command)

    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        channel = WeComChannel(process=None, config=config)
        channel._ws_client = FakeWsClient()

        with caplog.at_level(logging.DEBUG):
            await channel.send(
                'chat_1',
                'hello',
                {
                    'req_id': 'req_stream_1',
                    'msgtype': 'stream',
                    'stream': {'id': 'stream_1', 'finish': True},
                },
            )

        messages = [record.getMessage() for record in caplog.records]
        assert any('wecom outbound stream payload:' in message and 'stream_id=stream_1' in message for message in messages)
        assert any('finish=True' in message and 'content_len=5' in message for message in messages)

    asyncio.run(run_case())


def test_send_stream_logs_do_not_emit_info_noise(caplog):
    class FakeWsClient:
        def __init__(self):
            self.commands = []

        async def send_command(self, command):
            self.commands.append(command)

    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        channel = WeComChannel(process=None, config=config)
        channel._ws_client = FakeWsClient()

        with caplog.at_level(logging.INFO):
            await channel.send(
                'chat_1',
                'hello',
                {
                    'req_id': 'req_stream_2',
                    'msgtype': 'stream',
                    'stream': {'id': 'stream_2', 'finish': False},
                },
            )

        messages = [record.getMessage() for record in caplog.records]
        assert not any('wecom outbound stream payload:' in message for message in messages)
        assert not any('wecom outbound send:' in message and 'msgtype=stream' in message for message in messages)

    asyncio.run(run_case())
