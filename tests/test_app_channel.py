import asyncio
from pathlib import Path
import tempfile

from wecom.app.channel import WeComAppChannel
from wecom.app.config import WeComAppConfig


class RecordingRequester:
    def __init__(self):
        self.calls = []

    async def __call__(self, method, url, **kwargs):
        self.calls.append({'method': method, 'url': url, **kwargs})
        if url.endswith('/cgi-bin/gettoken'):
            return {'errcode': 0, 'access_token': 'token_123', 'expires_in': 7200}
        if url.endswith('/cgi-bin/media/get'):
            return {
                'content': b'binary-file-content',
                'filename': 'report.pdf',
                'content_type': 'application/pdf',
            }
        if url.endswith('/cgi-bin/media/upload'):
            return {'errcode': 0, 'type': 'file', 'media_id': 'MEDIA_UPLOAD_001', 'created_at': '1710000000'}
        if url.endswith('/cgi-bin/message/send'):
            return {'errcode': 0, 'msgid': 'msg_send_001'}
        raise AssertionError(f'unexpected URL: {url}')


class FakeFilePart:
    type = 'file'

    def __init__(self, file_url):
        self.file_url = file_url


def test_handle_plaintext_callback_xml_persists_media_and_enqueues():
    async def run_case():
        with tempfile.TemporaryDirectory() as temp_dir:
            requester = RecordingRequester()
            config = WeComAppConfig.from_mapping(
                {
                    'corp_id': 'ww1234567890',
                    'agent_secret': 'secret_123',
                    'agent_id': 1000001,
                    'media_dir': temp_dir,
                    'api_request_func': requester,
                }
            )
            channel = WeComAppChannel(process=None, config=config)
            enqueued = []
            channel._enqueue = lambda payload: enqueued.append(payload)

            xml_text = (
                '<xml>'
                '<ToUserName><![CDATA[ww1234567890]]></ToUserName>'
                '<FromUserName><![CDATA[zhangsan]]></FromUserName>'
                '<CreateTime>1710000000</CreateTime>'
                '<MsgType><![CDATA[file]]></MsgType>'
                '<MediaId><![CDATA[MEDIA_ID_001]]></MediaId>'
                '<FileName><![CDATA[report.pdf]]></FileName>'
                '<MsgId>1234567890123456</MsgId>'
                '<AgentID>1000001</AgentID>'
                '</xml>'
            )

            result = await channel.handle_plaintext_callback_xml(xml_text)

            assert result == 'success'
            assert len(enqueued) == 1
            attachment = enqueued[0]['attachments'][0]
            assert attachment['local_path'].endswith('report.pdf')
            assert Path(attachment['local_path']).exists()
            assert Path(attachment['local_path']).read_bytes() == b'binary-file-content'

    asyncio.run(run_case())


def test_app_channel_send_media_uploads_then_sends_message():
    async def run_case():
        with tempfile.TemporaryDirectory() as temp_dir:
            requester = RecordingRequester()
            file_path = Path(temp_dir) / 'report.txt'
            file_path.write_text('hello media', encoding='utf-8')

            config = WeComAppConfig.from_mapping(
                {
                    'corp_id': 'ww1234567890',
                    'agent_secret': 'secret_123',
                    'agent_id': 1000001,
                    'api_request_func': requester,
                }
            )
            channel = WeComAppChannel(process=None, config=config)

            response = await channel.send_media(
                'zhangsan',
                FakeFilePart(file_path.as_uri()),
            )

            assert response['msgid'] == 'msg_send_001'
            upload_calls = [call for call in requester.calls if call['url'].endswith('/cgi-bin/media/upload')]
            send_calls = [call for call in requester.calls if call['url'].endswith('/cgi-bin/message/send')]
            assert len(upload_calls) == 1
            assert len(send_calls) == 1
            assert send_calls[0]['json']['file']['media_id'] == 'MEDIA_UPLOAD_001'

    asyncio.run(run_case())
