from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WeComAppSendTarget:
    touser: str = ''
    toparty: str = ''
    totag: str = ''
    chatid: str = ''

    @property
    def is_appchat(self) -> bool:
        return bool(self.chatid)

    def apply_to_payload(self, payload: dict) -> dict:
        if self.chatid:
            payload['chatid'] = self.chatid
            return payload
        if self.touser:
            payload['touser'] = self.touser
        if self.toparty:
            payload['toparty'] = self.toparty
        if self.totag:
            payload['totag'] = self.totag
        return payload


@dataclass(slots=True)
class WeComDownloadedMedia:
    content: bytes
    filename: str
    content_type: str
