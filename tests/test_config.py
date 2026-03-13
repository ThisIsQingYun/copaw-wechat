from wecom.config import WeComConfig


def test_policy_values_keep_builtin_keys():
    config = WeComConfig.from_mapping(
        {
            'bot_id': '',
            'secret': '',
            'dm_policy': 'open',
            'group_policy': 'allowlist',
        }
    )

    assert config.dm_policy == 'open'
    assert config.group_policy == 'allowlist'


def test_policy_values_accept_chinese_labels_and_normalize():
    config = WeComConfig.from_mapping(
        {
            'bot_id': '',
            'secret': '',
            'dm_policy': '开放',
            'group_policy': '白名单列表',
        }
    )

    assert config.dm_policy == 'open'
    assert config.group_policy == 'allowlist'
