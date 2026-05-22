import importlib


def test_app_package_imports():
    # 验证 app 包可以被正常导入。
    assert importlib.import_module("app")
