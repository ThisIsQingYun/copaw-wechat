from wecom.app.callback import WeComAppCallbackHandler
from wecom.crypto import WeComCrypto


AES_KEY = '0123456789abcdef0123456789abcdef'


def test_app_callback_handler_verifies_url():
    crypto = WeComCrypto(token='token_123', encoding_aes_key=AES_KEY, receive_id='ww123')
    encrypted = crypto.encrypt_text('hello', timestamp='1710000000', nonce='nonce_1')
    handler = WeComAppCallbackHandler(
        token='token_123',
        encoding_aes_key=AES_KEY,
        receive_id='ww123',
    )

    result = handler.handle_url_verification(
        {
            'msg_signature': encrypted['msgsignature'],
            'timestamp': '1710000000',
            'nonce': 'nonce_1',
            'echostr': encrypted['encrypt'],
        }
    )

    assert result == 'hello'


def test_app_callback_handler_decrypts_message_xml():
    plaintext_xml = (
        '<xml>'
        '<ToUserName><![CDATA[ww123]]></ToUserName>'
        '<FromUserName><![CDATA[zhangsan]]></FromUserName>'
        '<CreateTime>1710000000</CreateTime>'
        '<MsgType><![CDATA[text]]></MsgType>'
        '<Content><![CDATA[你好]]></Content>'
        '<MsgId>1234567890123456</MsgId>'
        '<AgentID>1000001</AgentID>'
        '</xml>'
    )
    crypto = WeComCrypto(token='token_123', encoding_aes_key=AES_KEY, receive_id='ww123')
    encrypted = crypto.encrypt_text(plaintext_xml, timestamp='1710000000', nonce='nonce_2')
    body_xml = f'<xml><Encrypt><![CDATA[{encrypted["encrypt"]}]]></Encrypt></xml>'
    handler = WeComAppCallbackHandler(
        token='token_123',
        encoding_aes_key=AES_KEY,
        receive_id='ww123',
    )

    decrypted_xml, parsed = handler.decrypt_callback_xml(
        query={
            'msg_signature': encrypted['msgsignature'],
            'timestamp': '1710000000',
            'nonce': 'nonce_2',
        },
        body_xml=body_xml,
    )

    assert '<MsgType><![CDATA[text]]></MsgType>' in decrypted_xml
    assert parsed['Content'] == '你好'
