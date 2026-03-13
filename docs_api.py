from __future__ import annotations

import inspect
from enum import IntEnum
from typing import Any, Awaitable, Callable, Mapping


CONTENT_TYPE_MARKDOWN = 1


class WeComDocType(IntEnum):
    DOC = 3
    SMARTSHEET = 10


ToolCaller = Callable[[str, dict[str, Any]], Any]


def build_create_doc_args(*, doc_name: str, doc_type: WeComDocType | int = WeComDocType.DOC) -> dict[str, Any]:
    return {
        'doc_type': int(doc_type),
        'doc_name': doc_name,
    }


def build_edit_doc_content_args(
    *,
    docid: str,
    content: str,
    content_type: int = CONTENT_TYPE_MARKDOWN,
) -> dict[str, Any]:
    return {
        'docid': docid,
        'content': content,
        'content_type': int(content_type),
    }


def build_smartsheet_add_sheet_args(
    *,
    docid: str,
    title: str | None = None,
    properties: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'docid': docid}
    merged = dict(properties or {})
    if title is not None:
        merged['title'] = title
    if merged:
        payload['properties'] = merged
    return payload


def build_smartsheet_get_sheet_args(*, docid: str) -> dict[str, Any]:
    return {'docid': docid}


def build_smartsheet_add_fields_args(*, docid: str, sheet_id: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'docid': docid,
        'sheet_id': sheet_id,
        'fields': [dict(field) for field in fields],
    }


def build_smartsheet_update_fields_args(*, docid: str, sheet_id: str, fields: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'docid': docid,
        'sheet_id': sheet_id,
        'fields': [dict(field) for field in fields],
    }


def build_smartsheet_get_fields_args(*, docid: str, sheet_id: str) -> dict[str, Any]:
    return {
        'docid': docid,
        'sheet_id': sheet_id,
    }


def build_smartsheet_add_records_args(*, docid: str, sheet_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        'docid': docid,
        'sheet_id': sheet_id,
        'records': [dict(record) for record in records],
    }


def text_cell(text: str, *, link: str | None = None) -> dict[str, Any]:
    cell = {
        'type': 'url' if link else 'text',
        'text': text,
    }
    if link is not None:
        cell['link'] = link
    return cell


def url_cell(link: str, *, text: str | None = None) -> dict[str, Any]:
    cell = {
        'type': 'url',
        'link': link,
    }
    if text is not None:
        cell['text'] = text
    return cell


def image_cell(
    image_url: str,
    *,
    image_id: str | None = None,
    title: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, Any]:
    cell = {'image_url': image_url}
    if image_id is not None:
        cell['id'] = image_id
    if title is not None:
        cell['title'] = title
    if width is not None:
        cell['width'] = width
    if height is not None:
        cell['height'] = height
    return cell


def user_cell(user_id: str) -> dict[str, Any]:
    return {'user_id': user_id}


def option(text: str, *, option_id: str | None = None, style: int | None = None) -> dict[str, Any]:
    payload = {'text': text}
    if option_id is not None:
        payload['id'] = option_id
    if style is not None:
        payload['style'] = style
    return payload


def location_cell(*, location_id: str, latitude: str, longitude: str, title: str, source_type: int = 1) -> dict[str, Any]:
    return {
        'source_type': source_type,
        'id': location_id,
        'latitude': latitude,
        'longitude': longitude,
        'title': title,
    }


class WeComDocsToolClient:
    def __init__(self, *, call_tool: ToolCaller):
        self._call_tool = call_tool

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        result = self._call_tool(tool_name, arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def create_doc(self, *, doc_name: str, doc_type: WeComDocType | int = WeComDocType.DOC) -> Any:
        return await self.call('create_doc', build_create_doc_args(doc_name=doc_name, doc_type=doc_type))

    async def edit_doc_content(self, *, docid: str, content: str, content_type: int = CONTENT_TYPE_MARKDOWN) -> Any:
        return await self.call(
            'edit_doc_content',
            build_edit_doc_content_args(docid=docid, content=content, content_type=content_type),
        )

    async def smartsheet_add_sheet(
        self,
        *,
        docid: str,
        title: str | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> Any:
        return await self.call(
            'smartsheet_add_sheet',
            build_smartsheet_add_sheet_args(docid=docid, title=title, properties=properties),
        )

    async def smartsheet_get_sheet(self, *, docid: str) -> Any:
        return await self.call('smartsheet_get_sheet', build_smartsheet_get_sheet_args(docid=docid))

    async def smartsheet_add_fields(self, *, docid: str, sheet_id: str, fields: list[dict[str, Any]]) -> Any:
        return await self.call(
            'smartsheet_add_fields',
            build_smartsheet_add_fields_args(docid=docid, sheet_id=sheet_id, fields=fields),
        )

    async def smartsheet_update_fields(self, *, docid: str, sheet_id: str, fields: list[dict[str, Any]]) -> Any:
        return await self.call(
            'smartsheet_update_fields',
            build_smartsheet_update_fields_args(docid=docid, sheet_id=sheet_id, fields=fields),
        )

    async def smartsheet_get_fields(self, *, docid: str, sheet_id: str) -> Any:
        return await self.call(
            'smartsheet_get_fields',
            build_smartsheet_get_fields_args(docid=docid, sheet_id=sheet_id),
        )

    async def smartsheet_add_records(self, *, docid: str, sheet_id: str, records: list[dict[str, Any]]) -> Any:
        return await self.call(
            'smartsheet_add_records',
            build_smartsheet_add_records_args(docid=docid, sheet_id=sheet_id, records=records),
        )
