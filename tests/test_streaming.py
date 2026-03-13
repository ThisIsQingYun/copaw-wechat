import asyncio
from types import SimpleNamespace

from wecom.channel import WeComChannel
from wecom.config import WeComConfig


class FakeTextPart:
    def __init__(self, text: str, *, delta: bool = False):
        self.type = 'text'
        self.text = text
        self.delta = delta


class FakeFilePart:
    def __init__(self, file_url: str):
        self.type = 'file'
        self.file_url = file_url
        self.file_id = None
        self.filename = None
        self.file_data = None


class FakeMessageEvent:
    def __init__(self, *, status: str, message_id: str, content):
        self.object = 'message'
        self.status = status
        self.id = message_id
        self.type = 'message'
        self.content = list(content)


class FakeContentEvent:
    def __init__(self, *, status: str, message_id: str, text: str, delta: bool = True):
        self.object = 'content'
        self.status = status
        self.type = 'text'
        self.msg_id = message_id
        self.text = text
        self.delta = delta


class FakeResponseEvent:
    def __init__(self):
        self.object = 'response'
        self.status = 'completed'
        self.error = None


async def _run_loop(events):
    async def process(_request):
        for event in events:
            yield event

    config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
    channel = WeComChannel(process=process, config=config)

    sent_messages = []
    sent_parts = []
    reply_sent = []

    async def fake_send(to_handle, text, meta=None):
        sent_messages.append({'to_handle': to_handle, 'text': text, 'meta': dict(meta or {})})

    async def fake_send_content_parts(to_handle, parts, meta=None):
        sent_parts.append({'to_handle': to_handle, 'parts': list(parts), 'meta': dict(meta or {})})

    def fake_message_to_parts(message):
        return list(getattr(message, 'content', []) or [])

    async def fake_on_event_response(_request, _event):
        return None

    async def fake_on_consume_error(_request, _to_handle, err_text):
        raise AssertionError(f'unexpected consume error: {err_text}')

    channel.send = fake_send
    channel.send_content_parts = fake_send_content_parts
    channel._message_to_content_parts = fake_message_to_parts
    channel.on_event_response = fake_on_event_response
    channel._on_consume_error = fake_on_consume_error
    channel._get_response_error_message = lambda last_response: None
    channel._on_reply_sent = lambda *args: reply_sent.append(args)
    channel.get_on_reply_sent_args = lambda request, to_handle: (getattr(request, 'user_id', ''), getattr(request, 'session_id', ''))

    request = SimpleNamespace(user_id='user_1', session_id='session_1')
    meta = {'response_url': 'https://example.com/response'}
    await channel._run_process_loop(request, 'chat_1', meta)
    return sent_messages, sent_parts, reply_sent


def test_run_process_loop_streams_message_deltas_without_duplicate_final_text():
    async def run_case():
        events = [
            FakeMessageEvent(status='in_progress', message_id='msg_1', content=[FakeTextPart('你')]),
            FakeMessageEvent(status='in_progress', message_id='msg_1', content=[FakeTextPart('你好')]),
            FakeMessageEvent(status='completed', message_id='msg_1', content=[FakeTextPart('你好')]),
            FakeResponseEvent(),
        ]
        sent_messages, sent_parts, reply_sent = await _run_loop(events)

        assert [item['text'] for item in sent_messages] == ['你', '好']
        assert all(item['meta'].get('msgtype') == 'stream' for item in sent_messages)
        assert sent_parts == []
        assert reply_sent == [('wecom', 'user_1', 'session_1')]

    asyncio.run(run_case())


def test_run_process_loop_stream_completion_keeps_non_text_parts_only():
    async def run_case():
        events = [
            FakeContentEvent(status='in_progress', message_id='msg_2', text='hello '),
            FakeContentEvent(status='in_progress', message_id='msg_2', text='world'),
            FakeMessageEvent(
                status='completed',
                message_id='msg_2',
                content=[FakeTextPart('hello world'), FakeFilePart('https://example.com/result.txt')],
            ),
            FakeResponseEvent(),
        ]
        sent_messages, sent_parts, _ = await _run_loop(events)

        assert [item['text'] for item in sent_messages] == ['hello ', 'world']
        assert len(sent_parts) == 1
        assert len(sent_parts[0]['parts']) == 1
        assert sent_parts[0]['parts'][0].type == 'file'
        assert sent_parts[0]['parts'][0].file_url == 'https://example.com/result.txt'

    asyncio.run(run_case())
