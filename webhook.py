from __future__ import annotations

from typing import Any, Mapping

from wecom.crypto import WeComCrypto
from wecom.parsers.outbound import build_passive_update_body


class WeComWebhookHandler:
    def __init__(self, *, token: str, encoding_aes_key: str, receive_id: str = ''):
        self.crypto = WeComCrypto(token=token, encoding_aes_key=encoding_aes_key, receive_id=receive_id)

    def handle_url_verification(self, query: Mapping[str, Any]) -> str:
        signature = str(query.get('msg_signature') or query.get('msgsignature') or '')
        timestamp = str(query.get('timestamp') or '')
        nonce = str(query.get('nonce') or '')
        echostr = str(query.get('echostr') or '')
        return self.crypto.verify_url(msg_signature=signature, timestamp=timestamp, nonce=nonce, echostr=echostr)

    def decrypt_callback(self, *, query: Mapping[str, Any], body: Mapping[str, Any]) -> dict[str, Any]:
        encrypted = str(body.get('encrypt') or '')
        signature = str(query.get('msg_signature') or query.get('msgsignature') or '')
        timestamp = str(query.get('timestamp') or '')
        nonce = str(query.get('nonce') or '')
        if not self.crypto.verify_signature(encrypted=encrypted, timestamp=timestamp, nonce=nonce, signature=signature):
            raise ValueError('Invalid WeCom callback signature')
        return self.crypto.decrypt_object(encrypted)

    def encrypt_reply(self, reply_body: dict[str, Any], *, timestamp: str, nonce: str) -> dict[str, str]:
        return self.crypto.encrypt_object(reply_body, timestamp=timestamp, nonce=nonce)

    def build_passive_update_response(self, *, template_card: dict, userids: list[str] | None = None) -> dict:
        return build_passive_update_body(template_card=template_card, userids=userids)
