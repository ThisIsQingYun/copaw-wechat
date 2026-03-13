from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


_BLOCK_SIZE_BITS = 32 * 8


def _normalize_aes_key(aes_key: str | bytes) -> bytes:
    if isinstance(aes_key, bytes):
        if len(aes_key) in (16, 24, 32):
            return aes_key
        raise ValueError('AES key bytes must be 16, 24, or 32 bytes long')

    raw = aes_key.strip()
    if len(raw) in (43, 44):
        padded = raw + '=' * (-len(raw) % 4)
        decoded = base64.b64decode(padded)
        if len(decoded) in (16, 24, 32):
            return decoded
    encoded = raw.encode('utf-8')
    if len(encoded) in (16, 24, 32):
        return encoded
    raise ValueError('Unsupported AES key format')


def _encrypt_bytes(data: bytes, aes_key: bytes) -> bytes:
    padder = padding.PKCS7(_BLOCK_SIZE_BITS).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _decrypt_bytes(data: bytes, aes_key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(aes_key[:16]))
    decryptor = cipher.decryptor()
    padded = decryptor.update(data) + decryptor.finalize()
    unpadder = padding.PKCS7(_BLOCK_SIZE_BITS).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def encrypt_media_bytes(data: bytes, aes_key: str | bytes) -> bytes:
    return _encrypt_bytes(data, _normalize_aes_key(aes_key))


def decrypt_media_bytes(data: bytes, aes_key: str | bytes) -> bytes:
    return _decrypt_bytes(data, _normalize_aes_key(aes_key))


@dataclass(slots=True)
class WeComCrypto:
    token: str
    encoding_aes_key: str
    receive_id: str = ''
    _aes_key: bytes = field(init=False, repr=False)
    _receive_id_bytes: bytes = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._aes_key = _normalize_aes_key(self.encoding_aes_key)
        self._receive_id_bytes = self.receive_id.encode('utf-8')

    def encrypt_text(self, plaintext: str, *, timestamp: str, nonce: str) -> dict[str, str]:
        return self._encrypt_raw(plaintext.encode('utf-8'), timestamp=timestamp, nonce=nonce)

    def decrypt_text(self, encrypted: str) -> str:
        data = self._decrypt_message(encrypted)
        return data.decode('utf-8')

    def encrypt_object(self, payload: dict[str, Any], *, timestamp: str, nonce: str) -> dict[str, str]:
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return self._encrypt_raw(raw, timestamp=timestamp, nonce=nonce)

    def decrypt_object(self, encrypted: str) -> dict[str, Any]:
        return json.loads(self.decrypt_text(encrypted))

    def verify_signature(self, *, encrypted: str, timestamp: str, nonce: str, signature: str) -> bool:
        expected = self.generate_signature(self.token, timestamp, nonce, encrypted)
        return expected == signature

    def verify_url(self, *, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        if not self.verify_signature(encrypted=echostr, timestamp=timestamp, nonce=nonce, signature=msg_signature):
            raise ValueError('Invalid WeCom callback signature')
        return self.decrypt_text(echostr)

    @staticmethod
    def generate_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
        joined = ''.join(sorted([token, timestamp, nonce, encrypted]))
        return hashlib.sha1(joined.encode('utf-8')).hexdigest()

    def _encrypt_raw(self, payload: bytes, *, timestamp: str, nonce: str) -> dict[str, str]:
        random_prefix = os.urandom(16)
        msg_len = struct.pack('!I', len(payload))
        plaintext = random_prefix + msg_len + payload + self._receive_id_bytes
        encrypted = base64.b64encode(_encrypt_bytes(plaintext, self._aes_key)).decode('utf-8')
        signature = self.generate_signature(self.token, timestamp, nonce, encrypted)
        return {
            'encrypt': encrypted,
            'msgsignature': signature,
            'timestamp': str(timestamp),
            'nonce': str(nonce),
        }

    def _decrypt_message(self, encrypted: str) -> bytes:
        encrypted_bytes = base64.b64decode(encrypted)
        plaintext = _decrypt_bytes(encrypted_bytes, self._aes_key)
        msg_len = struct.unpack('!I', plaintext[16:20])[0]
        msg = plaintext[20:20 + msg_len]
        receive_id = plaintext[20 + msg_len:]
        if self._receive_id_bytes and receive_id != self._receive_id_bytes:
            raise ValueError('Receive ID mismatch in decrypted WeCom payload')
        return msg
