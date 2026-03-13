from wecom.crypto import decrypt_media_bytes, encrypt_media_bytes
from wecom.docs_api import WeComDocsToolClient
from wecom.ws.transport import build_aiohttp_transport_factory


def build_default_transport_factory(config):
    return build_aiohttp_transport_factory(config)


def decrypt_media(data: bytes, aes_key: str | bytes) -> bytes:
    return decrypt_media_bytes(data, aes_key)


def encrypt_media(data: bytes, aes_key: str | bytes) -> bytes:
    return encrypt_media_bytes(data, aes_key)


def create_docs_client(call_tool):
    return WeComDocsToolClient(call_tool=call_tool)
