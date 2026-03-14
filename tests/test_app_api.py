import asyncio

from wecom.app.api_client import WeComAppApiClient
from wecom.app.config import WeComAppConfig


class RecordingRequester:
    def __init__(self):
        self.calls = []

    async def __call__(self, method, url, **kwargs):
        self.calls.append({'method': method, 'url': url, **kwargs})
        if url.endswith('/cgi-bin/gettoken'):
            return {
                'errcode': 0,
                'access_token': 'token_123',
                'expires_in': 7200,
            }
        if url.endswith('/cgi-bin/message/send'):
            return {'errcode': 0, 'msgid': 'msg_text_001'}
        if url.endswith('/cgi-bin/appchat/send'):
            return {'errcode': 0, 'msgid': 'msg_group_001'}
        raise AssertionError(f'unexpected URL: {url}')


def test_app_api_client_sends_direct_message_and_caches_token():
    async def run_case():
        requester = RecordingRequester()
        config = WeComAppConfig.from_mapping(
            {
                'corp_id': 'ww1234567890',
                'agent_secret': 'secret_123',
                'agent_id': 1000001,
                'api_request_func': requester,
            }
        )
        client = WeComAppApiClient(config)

        first = await client.send_text('zhangsan', 'hello')
        second = await client.send_text('lisi', 'world')

        assert first['msgid'] == 'msg_text_001'
        assert second['msgid'] == 'msg_text_001'

        gettoken_calls = [call for call in requester.calls if call['url'].endswith('/cgi-bin/gettoken')]
        send_calls = [call for call in requester.calls if call['url'].endswith('/cgi-bin/message/send')]

        assert len(gettoken_calls) == 1
        assert len(send_calls) == 2
        assert send_calls[0]['json']['touser'] == 'zhangsan'
        assert send_calls[0]['json']['agentid'] == 1000001

    asyncio.run(run_case())


def test_app_api_client_sends_group_message_via_appchat():
    async def run_case():
        requester = RecordingRequester()
        config = WeComAppConfig.from_mapping(
            {
                'corp_id': 'ww1234567890',
                'agent_secret': 'secret_123',
                'agent_id': 1000001,
                'api_request_func': requester,
            }
        )
        client = WeComAppApiClient(config)

        response = await client.send_text(
            'chat_group_001',
            'hello group',
            meta={'use_appchat': True},
        )

        assert response['msgid'] == 'msg_group_001'

        appchat_calls = [call for call in requester.calls if call['url'].endswith('/cgi-bin/appchat/send')]
        assert len(appchat_calls) == 1
        assert appchat_calls[0]['json']['chatid'] == 'chat_group_001'

    asyncio.run(run_case())
