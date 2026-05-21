import importlib


def test_app_package_imports():
    assert importlib.import_module("app")
