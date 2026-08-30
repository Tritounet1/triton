"""model_roles.py's ROLE_MODELS used to be the only way to pick a model for
a multi-agent role - changing it meant editing code. These pin down the
settings.json-backed override added on top of it: an override takes
priority when set, model_for_role() reflects a change immediately (no
restart, like get_model()), and clearing it falls back to the built-in
default again."""

from unittest.mock import patch

from triton import model_roles, settings


def test_load_role_model_overrides_ignores_malformed_data():
    with patch.object(settings, "_load", return_value={}):
        assert settings.load_role_model_overrides() == {}
    with patch.object(settings, "_load", return_value={"role_models": "not a dict"}):
        assert settings.load_role_model_overrides() == {}
    with patch.object(
        settings,
        "_load",
        return_value={"role_models": {"code": "real/model", "bad": 123, "empty": ""}},
    ):
        assert settings.load_role_model_overrides() == {"code": "real/model"}


def test_model_for_role_falls_back_to_the_built_in_default():
    with patch.object(model_roles, "load_role_model_overrides", return_value={}):
        assert model_roles.model_for_role("code") == model_roles.ROLE_MODELS["code"]


def test_model_for_role_uses_the_override_when_set():
    with patch.object(
        model_roles, "load_role_model_overrides", return_value={"code": "custom/model"}
    ):
        assert model_roles.model_for_role("code") == "custom/model"


def test_model_for_role_unknown_role_falls_back_to_default_role():
    with patch.object(model_roles, "load_role_model_overrides", return_value={}):
        assert model_roles.model_for_role("nonexistent") == model_roles.ROLE_MODELS["research"]


def test_save_role_model_override_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")

    settings.save_role_model_override("code", "custom/model")
    assert settings.load_role_model_overrides() == {"code": "custom/model"}

    settings.save_role_model_override("research", "another/model")
    assert settings.load_role_model_overrides() == {
        "code": "custom/model",
        "research": "another/model",
    }

    settings.save_role_model_override("code", None)
    assert settings.load_role_model_overrides() == {"research": "another/model"}
