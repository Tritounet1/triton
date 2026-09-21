from triton.paths import _compute_root_dir


def test_configured_data_directory_overrides_default(monkeypatch, tmp_path):
    data_dir = tmp_path / "triton-data"
    monkeypatch.setenv("TRITON_DATA_DIR", str(data_dir))

    assert _compute_root_dir() == data_dir
