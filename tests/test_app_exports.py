from wecom import WeComAppChannel


def test_wecom_package_exports_self_built_app_channel():
    assert WeComAppChannel.channel == 'wecom_app'
