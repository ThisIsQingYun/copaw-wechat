from __future__ import annotations

from typing import Any, Mapping

from wecom.crypto import WeComCrypto

from .parser import parse_plaintext_xml


def _extract_encrypt_value(xml_text: str) -> str:
    parsed = parse_plaintext_xml(xml_text)
    encrypted = str(parsed.get('Encrypt', '')).strip()
    if not encrypted:
        raise ValueError('Missing Encrypt field in WeCom callback body')
    return encrypted


def _build_encrypted_reply_xml(payload: dict[str, str]) -> str:
    return (
        '<xml>'
        f'<Encrypt><![CDATA[{payload["encrypt"]}]]></Encrypt>'
        f'<MsgSignature><![CDATA[{payload["msgsignature"]}]]></MsgSignature>'
        f'<TimeStamp>{payload["timestamp"]}</TimeStamp>'
        f'<Nonce><![CDATA[{payload["nonce"]}]]></Nonce>'
        '</xml>'
    )


class WeComAppCallbackHandler:
    def __init__(self, *, token: str, encoding_aes_key: str, receive_id: str = ''):
        self.crypto = WeComCrypto(token=token, encoding_aes_key=encoding_aes_key, receive_id=receive_id)

    def handle_url_verification(self, query: Mapping[str, Any]) -> str:
        signature = str(query.get('msg_signature') or query.get('msgsignature') or '')
        timestamp = str(query.get('timestamp') or '')
        nonce = str(query.get('nonce') or '')
        echostr = str(query.get('echostr') or '')
        return self.crypto.verify_url(msg_signature=signature, timestamp=timestamp, nonce=nonce, echostr=echostr)

    def decrypt_callback_xml(self, *, query: Mapping[str, Any], body_xml: str) -> tuple[str, dict[str, str]]:
        encrypted = _extract_encrypt_value(body_xml)
        signature = str(query.get('msg_signature') or query.get('msgsignature') or '')
        timestamp = str(query.get('timestamp') or '')
        nonce = str(query.get('nonce') or '')
        if not self.crypto.verify_signature(
            encrypted=encrypted,
            timestamp=timestamp,
            nonce=nonce,
            signature=signature,
        ):
            raise ValueError('Invalid WeCom callback signature')
        plaintext_xml = self.crypto.decrypt_text(encrypted)
        return plaintext_xml, parse_plaintext_xml(plaintext_xml)

    def encrypt_reply_xml(self, reply_xml: str, *, timestamp: str, nonce: str) -> str:
        payload = self.crypto.encrypt_text(reply_xml, timestamp=timestamp, nonce=nonce)
        return _build_encrypted_reply_xml(payload)
