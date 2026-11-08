import json

from tools.replay_python_baseline import FIXTURE, replay


def test_frozen_python_stages():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert replay(fixture) == fixture["expected"]


def test_baseline_exercises_relations_and_packets():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    stages = replay(fixture)["stages"]
    assert stages["clone"]["pairs"]
    assert stages["skeleton"]["pairs"]
    assert stages["candidates"]["candidates"]
    assert stages["packets"]
