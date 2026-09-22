"""Remembered evaluation-form inputs + data-dir resolution."""

from app.core import paths, prefs


def test_prefs_round_trip_and_mode(tmp_path):
    path = tmp_path / "preferences.json"
    data = prefs.snapshot(
        {"product_description": "Bottle", "location": "Austin", "interests": "running"},
        8, ["clarity"])
    prefs.save_prefs(data, path)
    assert prefs.load_prefs(path) == data
    assert (path.stat().st_mode & 0o777) == 0o644  # non-secret file
    prefs.clear_prefs(path)
    assert prefs.load_prefs(path) == {}


def test_prefs_helpers_and_no_image():
    data = prefs.snapshot(
        {"product_description": "Bottle", "age_min": "25", "age_max": "40"},
        9, ["clarity", "relevance"])
    assert prefs.form_values(data)["product_description"] == "Bottle"
    assert prefs.persona_count(data, 12) == 9
    assert prefs.question_ids(data) == ["clarity", "relevance"]
    assert prefs.persona_count({}, 12) == 12
    assert prefs.question_ids({}) == prefs.DEFAULT_QUESTIONS
    assert "image" not in data  # the uploaded creative is never stored


def test_data_dir_respects_env(tmp_path, monkeypatch):
    target = tmp_path / "data"
    monkeypatch.setenv("ADTESTPRO_DATA_DIR", str(target))
    assert paths.data_dir() == target
    assert paths.data_dir().is_dir()


def test_load_prefs_ignores_corrupt_file(tmp_path):
    path = tmp_path / "preferences.json"
    path.write_text("{not json", encoding="utf-8")
    assert prefs.load_prefs(path) == {}
