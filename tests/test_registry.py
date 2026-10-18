"""Fitness function: extensibility. A plugin registered only in config is usable without touching kb/core."""
from kb.core import registry


def test_new_connector_via_config_only(tmp_path):
    plugins = {"connectors": {"dummy": "tests.dummy_plugin:DummyConnector"}}
    c = registry.create("connectors", "dummy", plugins=plugins)
    assert list(c.list()) == ["a", "b"]
    assert c.fetch("a", tmp_path).path.read_text() == "a"


def test_default_plugins_resolve():
    for kind, items in registry.config.load("plugins").items():
        for name, spec in (items or {}).items():
            if kind == "secret_stores" and name == "keyring":
                continue  # optional dependency
            registry.resolve(spec)
