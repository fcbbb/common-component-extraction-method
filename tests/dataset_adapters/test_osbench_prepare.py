"""Validate OS-Bench preparation without Docker or model calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dataset_adapters import osbench


DATASET = (
    Path(__file__).resolve().parents[3]
    / "datasets"
    / "osbench"
    / "dataset"
    / "windows2linux_cpp.jsonl"
)

LOG_PARSER = """
def parser(log):
    return {}
"""


def row(instance_id: str = "owner__repo-1__cpp__linux__abc123") -> dict:
    return {
        "instance_id": instance_id,
        "repo": "owner/repo",
        "language": "cpp",
        "base_commit": "a" * 40,
        "FAIL_TO_PASS": ["One.test"],
        "PASS_TO_PASS": ["Two.test"],
        "difficulty": "hard",
        "docker_image": "example/osbench:" + instance_id,
        "log_parser": LOG_PARSER,
        "metadata": {"task_type": "cross_platform_migration", "files_modified": 2},
        "migration_direction": "windows_to_linux",
        "patch": "diff --git a/a b/a\n",
        "print_cmds": ["cat output.log"],
        "problem_statement": "Migrate this repository to Linux and pass all tests.",
        "rebuild_cmds": ["cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON"],
        "test_cmds": ["ctest --test-dir build"],
        "test_patch": "",
    }


def write_dataset(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(value) for value in rows) + "\n", encoding="utf-8"
    )
    return path


def test_load_rows_normalizes_and_rejects_unsupported_language(tmp_path):
    value = row()
    value["patch"] = "diff --git a/a b/a\n context\n \n"
    path = write_dataset(tmp_path / "tasks.jsonl", [value])
    rows = osbench.load_rows(path, expected_count=1)
    assert rows[0]["schema"] == osbench.SCHEMA
    assert rows[0]["test_patch"] == ""
    assert rows[0]["patch"] == value["patch"]

    invalid = row("owner__repo-2__cs__linux__def456")
    invalid["language"] = "cs"
    with pytest.raises(ValueError, match="not supported"):
        osbench.normalize_row(invalid, line_number=1)


def test_log_parser_must_define_parser():
    value = row()
    value["log_parser"] = "def other(log):\n    return {}\n"
    with pytest.raises(ValueError, match="parser"):
        osbench.normalize_row(value, line_number=1)


def test_normalize_compile_commands_rewrites_container_paths(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    payload = [
        {
            "directory": "/testbed/build",
            "file": "../src/a.cpp",
            "arguments": [
                "g++",
                "-I/testbed/include",
                "-DDEBUG",
                "-std=gnu++17",
                "-c",
                "../src/a.cpp",
                "-o",
                "CMakeFiles/a.o",
            ],
        }
    ]
    normalized = osbench.normalize_compile_commands(payload, snapshot)
    assert normalized == [
        {
            "directory": "build",
            "file": "../src/a.cpp",
            "arguments": ["-I../include", "-DDEBUG", "-std=gnu++17"],
        }
    ]


def test_normalize_compile_commands_rejects_escape(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(ValueError, match="escapes"):
        osbench.normalize_compile_commands(
            [
                {
                    "directory": "/testbed/build",
                    "file": "../../outside.cpp",
                    "arguments": ["g++", "-c", "../../outside.cpp"],
                }
            ],
            snapshot,
        )


def test_write_task_package_and_source_stats(tmp_path):
    snapshot = tmp_path / "source_snapshot"
    (snapshot / "src").mkdir(parents=True)
    (snapshot / "include").mkdir()
    (snapshot / "src" / "a.cpp").write_text("int a() { return 1; }\n", encoding="utf-8")
    (snapshot / "include" / "a.h").write_text("int a();\n", encoding="utf-8")
    (snapshot / "build").mkdir()
    (snapshot / "build" / "compile_commands.json").write_text("[]", encoding="utf-8")

    value = row()
    destination = tmp_path / "offline_task"
    dataset_path = tmp_path / "tasks.jsonl"
    dataset_path.write_text(json.dumps(value) + "\n", encoding="utf-8")
    images = {
        "official_image": "example/official:1",
        "official_image_id": "sha256:official",
        "prepared_image": "example/prepared:1",
        "prepared_image_id": "sha256:prepared",
        "runtime_image": "example/prepared:1",
        "runtime_image_id": "sha256:prepared",
        "runtime_image_source": "prepared",
    }
    osbench.write_task_package(
        value,
        snapshot,
        {"status": "ok", "source": "snapshot-build", "path": "compile_commands.json"},
        images,
        destination,
        dataset_path=dataset_path,
    )
    public = json.loads((destination / "task.json").read_text())
    private = json.loads((destination / "evaluation_only" / "task_private.json").read_text())
    provenance = json.loads((destination / "provenance.json").read_text())
    assert public["instance_id"] == value["instance_id"]
    assert public["language"] == "cpp"
    assert public["image_name"] == "example/prepared:1"
    assert private["install_config"]["test_cmd"] == value["test_cmds"]
    assert private["install_config"]["log_parser_source"] == LOG_PARSER
    assert (destination / "evaluation_only" / "osbench_log_parser.py").is_file()
    assert provenance["source_stats"]["source_files"] == 2
    assert provenance["source_stats"]["source_by_suffix"] == {".cpp": 1, ".h": 1}


def test_prepare_osbench_writes_workspace_without_docker(tmp_path, monkeypatch):
    dataset = write_dataset(tmp_path / "tasks.jsonl", [row()])
    project = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"

    def fake_images(current, *, image_prefix=None):
        return {
            "official_image": current["docker_image"],
            "official_image_id": "sha256:official",
            "prepared_image": "example/prepared:" + current["instance_id"],
            "prepared_image_id": "sha256:prepared",
            "runtime_image": "example/prepared:" + current["instance_id"],
            "runtime_image_id": "sha256:prepared",
            "runtime_image_source": "prepared",
        }

    def fake_materialize(image, destination, *, refresh=False, container_repository="/testbed"):
        (destination / "src").mkdir(parents=True)
        (destination / "src" / "a.cpp").write_text("int a() { return 1; }\n")
        (destination / "build").mkdir()
        (destination / "build" / "compile_commands.json").write_text("[]")
        return destination

    monkeypatch.setattr(osbench, "resolve_images", fake_images)
    monkeypatch.setattr(osbench, "materialize_source", fake_materialize)
    monkeypatch.setattr(
        osbench,
        "collect_compile_commands",
        lambda snapshot, current, image, mode="auto": {
            "status": "ok",
            "source": "fixture",
            "path": "compile_commands.json",
            "command_count": 1,
        },
    )
    summary = osbench.prepare_osbench(
        dataset,
        workspace,
        project,
        expected_count=1,
        api_base="https://example.invalid/v1",
    )
    assert summary["task_count"] == 1
    assert (workspace / "repository").resolve() == project.resolve()
    assert (workspace / "config.json").is_file()
    tasks = json.loads((workspace / "tasks.json").read_text())["tasks"]
    assert tasks[0]["instance_id"] == row()["instance_id"]
    assert tasks[0]["languages"][0]["id"] == "cpp"
    task_root = workspace / "tasks" / row()["instance_id"]
    config = json.loads((task_root / "config.json").read_text())
    assert config["runtime_image"].startswith("example/prepared:")
    assert config["languages"][0]["standard"] == "c++17"
    assert (workspace / "offline_artifacts" / "tasks" / row()["instance_id"] / "task.json").is_file()


@pytest.mark.skipif(not DATASET.is_file(), reason="OS-Bench dataset is not present")
def test_actual_osbench_dataset_contains_six_cpp_tasks():
    rows = osbench.load_rows(DATASET, expected_count=6)
    assert len(rows) == 6
    assert {row["language"] for row in rows} == {"cpp"}
    assert len({row["instance_id"] for row in rows}) == 6
    assert all(row["docker_image"].startswith("repolaunch/osbench:") for row in rows)
    assert all(row["migration_direction"] == "windows_to_linux" for row in rows)
    assert all(row["FAIL_TO_PASS"] for row in rows)
    assert all(row["test_patch"] == "" for row in rows)