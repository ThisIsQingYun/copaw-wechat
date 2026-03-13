import asyncio
import shutil
import uuid
from pathlib import Path

from wecom.config import WeComConfig
from wecom.crypto import encrypt_media_bytes
from wecom.models import InboundEnvelope


WORKSPACE_TMP = Path('D:/Software/codex/copaw-wechat/.tmp-tests')
WORKSPACE_TMP.mkdir(exist_ok=True)


def _make_case_dir(name: str) -> Path:
    path = WORKSPACE_TMP / f'{name}-{uuid.uuid4().hex}'
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_media_store_persists_media_and_decrypts_bytes():
    from wecom.media_store import WeComMediaStore

    async def run_case():
        case_dir = _make_case_dir('media-store')
        try:
            raw = b'hello wecom media'
            encrypted = encrypt_media_bytes(raw, '12345678901234567890123456789012')

            async def fetch(url: str) -> bytes:
                assert url == 'https://example.com/file.bin'
                return encrypted

            store = WeComMediaStore(
                media_dir=str(case_dir),
                fetch_func=fetch,
            )
            payload = {
                'attachments': [
                    {
                        'type': 'file',
                        'url': 'https://example.com/file.bin',
                        'aeskey': '12345678901234567890123456789012',
                    }
                ],
                'meta': {'msgid': 'msg_1'},
            }

            result = await store.persist_payload(payload)
            attachment = result['attachments'][0]
            saved = Path(attachment['local_path'])
            assert saved.exists()
            assert saved.read_bytes() == raw
            assert attachment['local_uri'].startswith('file:///')
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    asyncio.run(run_case())


def test_channel_handle_envelope_persists_media_before_enqueue():
    from wecom.channel import WeComChannel

    async def run_case():
        case_dir = _make_case_dir('channel-media')
        try:
            downloaded = b'image-bytes'

            async def fetch(url: str) -> bytes:
                assert url == 'https://example.com/demo.jpg'
                return downloaded

            config = WeComConfig.from_mapping(
                {
                    'bot_id': '',
                    'secret': '',
                    'media_dir': str(case_dir),
                    'media_fetch_func': fetch,
                }
            )
            channel = WeComChannel(process=None, config=config)
            envelope = InboundEnvelope(
                cmd='callback',
                req_id='req_1',
                body={
                    'msgid': 'msg_2',
                    'aibotid': 'bot_x',
                    'msgtype': 'image',
                    'from': {'userid': 'user_1'},
                    'image': {'url': 'https://example.com/demo.jpg'},
                },
            )

            payload = await channel._handle_envelope(envelope)
            attachment = payload['attachments'][0]
            assert Path(attachment['local_path']).exists()
            assert attachment['local_uri'].startswith('file:///')
        finally:
            shutil.rmtree(case_dir, ignore_errors=True)

    asyncio.run(run_case())
