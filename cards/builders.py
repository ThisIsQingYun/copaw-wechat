from __future__ import annotations


def _compact(value):
    if isinstance(value, dict):
        result = {k: _compact(v) for k, v in value.items() if v is not None}
        return {k: v for k, v in result.items() if v not in ({}, [])}
    if isinstance(value, list):
        result = [_compact(v) for v in value if v is not None]
        return [v for v in result if v not in ({}, [])]
    return value


def _card_action(action_url: str | None = None, *, appid: str | None = None, pagepath: str | None = None):
    if action_url:
        return {'type': 1, 'url': action_url}
    if appid:
        return {'type': 2, 'appid': appid, 'pagepath': pagepath}
    return None


def build_text_notice_card(*, title: str, description: str | None = None, action_url: str | None = None, **extra) -> dict:
    card = {
        'card_type': 'text_notice',
        'main_title': {'title': title, 'desc': description},
        'card_action': extra.pop('card_action', None) or _card_action(action_url),
        **extra,
    }
    return _compact(card)


def build_news_notice_card(*, title: str, description: str | None = None, image_url: str, article_url: str, **extra) -> dict:
    card = {
        'card_type': 'news_notice',
        'main_title': {'title': title, 'desc': description},
        'card_image': {'url': image_url, 'aspect_ratio': extra.pop('aspect_ratio', None)},
        'image_text_area': {
            'type': 1,
            'url': article_url,
            'title': title,
            'desc': description,
            'image_url': image_url,
        },
        **extra,
    }
    return _compact(card)


def build_button_interaction_card(*, title: str, description: str | None = None, task_id: str, buttons: list[dict], **extra) -> dict:
    card = {
        'card_type': 'button_interaction',
        'main_title': {'title': title, 'desc': description},
        'button_list': buttons,
        'task_id': task_id,
        **extra,
    }
    return _compact(card)


def build_vote_interaction_card(
    *,
    title: str,
    description: str | None = None,
    task_id: str,
    question_key: str,
    options: list[dict],
    submit_key: str,
    submit_text: str = '提交',
    **extra,
) -> dict:
    card = {
        'card_type': 'vote_interaction',
        'main_title': {'title': title, 'desc': description},
        'checkbox': {
            'question_key': question_key,
            'option_list': options,
            'disable': extra.pop('disable', None),
            'mode': extra.pop('mode', None),
        },
        'submit_button': {'text': submit_text, 'key': submit_key},
        'task_id': task_id,
        **extra,
    }
    return _compact(card)


def build_multiple_interaction_card(
    *,
    title: str,
    description: str | None = None,
    task_id: str,
    selects: list[dict],
    submit_text: str,
    submit_key: str,
    **extra,
) -> dict:
    card = {
        'card_type': 'multiple_interaction',
        'main_title': {'title': title, 'desc': description},
        'task_id': task_id,
        'select_list': selects,
        'submit_button': {'text': submit_text, 'key': submit_key},
        **extra,
    }
    return _compact(card)
