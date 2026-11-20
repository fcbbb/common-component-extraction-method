from __future__ import annotations

from pathlib import Path

import yaml

from migration_scenario_validation.shared.harness import agent_view, runner, taskmodel


def test_kylin_agent_view_omits_judge_tests_and_readme(tmp_path):
    source = tmp_path / "full"
    (source / "src").mkdir(parents=True)
    (source / "Foundation" / "testsuite").mkdir(parents=True)
    (source / "src" / "impl.cpp").write_text("source\n", encoding="utf-8")
    (source / "Foundation" / "testsuite" / "ThreadTest.cpp").write_text("judge\n", encoding="utf-8")
    (source / "TASK.md").write_text("hidden tests\n", encoding="utf-8")
    target = tmp_path / "agent"
    task = {"scenario": "windows_to_kylin"}

    result = agent_view.copy_agent_view(source, target, task)

    assert (target / "src" / "impl.cpp").read_text() == "source\n"
    assert not (target / "Foundation" / "testsuite").exists()
    assert not (target / "TASK.md").exists()
    assert "Foundation/testsuite/ThreadTest.cpp" in result["omitted"]


def test_musa_agent_view_omits_evaluator_and_utils(tmp_path):
    source = tmp_path / "full"
    (source / "reference").mkdir(parents=True)
    (source / "utils").mkdir(parents=True)
    (source / "src").mkdir(parents=True)
    (source / "reference" / "ref.py").write_text("contract\n", encoding="utf-8")
    (source / "utils" / "correctness.py").write_text("judge\n", encoding="utf-8")
    (source / "eval_single_runner.py").write_text("judge\n", encoding="utf-8")
    (source / "src" / "op.py").write_text("source\n", encoding="utf-8")
    target = tmp_path / "agent"
    task = {"scenario": "cuda_to_musa"}

    agent_view.copy_agent_view(source, target, task)

    assert (target / "reference" / "ref.py").exists()
    assert (target / "src" / "op.py").exists()
    assert not (target / "utils").exists()
    assert not (target / "eval_single_runner.py").exists()


def test_runner_overlays_agent_source_onto_full_judge_tree(tmp_path):
    task_root = tmp_path / "task"
    full = task_root / "work"
    agent = tmp_path / "agent"
    (full / "src").mkdir(parents=True)
    (full / "tests").mkdir(parents=True)
    (full / "src" / "impl.c").write_text("old\n", encoding="utf-8")
    (full / "tests" / "hidden.txt").write_text("judge-only\n", encoding="utf-8")
    (agent / "src").mkdir(parents=True)
    (agent / "src" / "impl.c").write_text("new\n", encoding="utf-8")
    task_root.mkdir(exist_ok=True)
    task = {
        "task_id": "overlay_demo",
        "scenario": "windows_to_kylin",
        "level": "L1",
        "source": {"repo": "synthetic", "commit": "-", "license": "synthetic"},
        "target": {},
        "spec": "implement src/impl.c",
        "build": {"mode": "none", "command": ""},
        "hidden_tests": {"command": "test -f {work}/tests/hidden.txt && grep -q new {work}/src/impl.c"},
        "gates": {"build": "none", "api_removal": "true", "behavior": "true"},
    }
    (task_root / "task.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

    result = runner.run(
        str(task_root),
        work_dir=str(agent),
        base_work_dir=str(full),
        skip_build=True,
        skip_api=True,
    )

    assert result["status"] == "pass"
    assert result["tests"] == "pass"
    assert result["agent_view"] == "filtered_overlay"


def test_agent_build_disables_test_targets():
    task = {
        "scenario": "windows_to_kylin",
        "build": {
            "command": "cmake -S . -B {build} -DBUILD_TESTS=ON -DENABLE_TESTS=ON -DBUILD_TESTING=ON"
        },
    }
    command = taskmodel.agent_build_command(task)
    assert "BUILD_TESTS=OFF" in command
    assert "ENABLE_TESTS=OFF" in command
    assert "BUILD_TESTING=OFF" in command


def test_migration_specs_and_readmes_do_not_leak_judge_material():
    import re
    import glob

    base = Path(__file__).resolve().parents[2] / "migration_scenario_validation"
    patterns = {
        "ipp_to_vsipl": r"vsip_|jvsip",
        "cuda_to_musa": r"load_inline|musa_sources|__global__|<<<|torch_musa",
        "windows_to_kylin": r"pthread_[A-Za-z0-9_]+|dlopen|dlsym|dlclose|OpenSSL|GTK|epoll|fork/exec",
    }
    for path in sorted(base.glob("*/tasks/*/task.yaml")) + sorted(base.glob("ipp_vsipl_tasks/*/task.yaml")):
        task = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenario = task["scenario"]
        assert not re.search(patterns[scenario], task.get("spec", "")), (task["task_id"], scenario)
    for path in sorted(base.glob("windows_to_kylin/tasks/*/README.md")) + sorted(base.glob("cuda_to_musa/tasks/*/README.md")):
        text = path.read_text(encoding="utf-8")
        assert "## Hidden tests" not in text, path
    assert not list(base.glob("*/tasks/*/work/TASK.md"))


def test_ipp_agent_view_sanitizes_evaluator_cmake(tmp_path):
    source = tmp_path / "full"
    source.mkdir()
    cmake = """cmake_minimum_required(VERSION 3.10)
project(demo C)
set(HARNESS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/harness")
option(USE_IPP "Build against Intel IPP (golden generation)" OFF)
option(USE_GOLD "Build the reference VSIPL migration (evaluator only)" OFF)
option(BUILD_HIDDEN_TESTS "Build the evaluator-only hidden test" OFF)
if(USE_GOLD)
    set(SRC ${CMAKE_CURRENT_SOURCE_DIR}/gold/demo_vsipl.c)
else()
    file(GLOB SRC ${CMAKE_CURRENT_SOURCE_DIR}/src/*.c)
endif()
if(USE_IPP)
    target_include_directories(demo PRIVATE ${IPP_ROOT}/include)
endif()
if(BUILD_HIDDEN_TESTS)
    add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)
endif()
add_executable(public_test test/public_test.c)
if(USE_IPP OR USE_GOLD)
    add_executable(golden_gen ${HARNESS_DIR}/golden_gen.c)
endif()
"""
    (source / "CMakeLists.txt").write_text(cmake, encoding="utf-8")
    (source / "test").mkdir()
    (source / "test" / "public_test.c").write_text("public\n", encoding="utf-8")
    target = tmp_path / "agent"
    task = {"scenario": "ipp_to_vsipl"}

    result = agent_view.copy_agent_view(source, target, task)
    text = (target / "CMakeLists.txt").read_text(encoding="utf-8")

    assert "HARNESS_DIR" not in text
    assert "BUILD_HIDDEN_TESTS" not in text
    assert "hidden_test" not in text
    assert "golden_gen" not in text
    assert "USE_IPP" not in text
    assert "USE_GOLD" not in text
    assert "public_test" in text
    assert "file(GLOB SRC" in text
    assert result["omitted"] == []


def test_judge_overlay_keeps_pristine_ipp_cmake(tmp_path):
    full = tmp_path / "full"
    agent = tmp_path / "agent"
    full.mkdir()
    agent.mkdir()
    pristine = "add_executable(hidden_test ${HARNESS_DIR}/hidden_test.c)\n"
    sanitized = "add_executable(public_test test/public_test.c)\n"
    (full / "CMakeLists.txt").write_text(pristine, encoding="utf-8")
    (agent / "CMakeLists.txt").write_text(sanitized, encoding="utf-8")
    (agent / "src").mkdir()
    (agent / "src" / "impl.c").write_text("new\n", encoding="utf-8")
    task = {"scenario": "ipp_to_vsipl"}

    result = agent_view.copy_overlay(agent, full, task)

    assert (full / "CMakeLists.txt").read_text() == pristine
    assert (full / "src" / "impl.c").read_text() == "new\n"
    assert "CMakeLists.txt" in result["omitted"]


def test_kylin_agent_view_filters_docs_and_test_build_files(tmp_path):
    source = tmp_path / "full"
    source.mkdir()
    (source / ".github").mkdir()
    (source / "docs").mkdir()
    (source / "test").mkdir()
    (source / "src").mkdir()
    (source / ".github" / "ci.yml").write_text("run tests\n", encoding="utf-8")
    (source / "docs" / "README.md").write_text("test/test-list.h\n", encoding="utf-8")
    (source / "test" / "test-list.h").write_text("test\n", encoding="utf-8")
    (source / "README.md").write_text("run test/test-list.h\n", encoding="utf-8")
    (source / "ChangeLog").write_text("fix test/test-fs.c\n", encoding="utf-8")
    (source / "configure.ac").write_text("AC_CONFIG_FILES([test/Makefile])\n", encoding="utf-8")
    (source / "src" / "impl.c").write_text("source\n", encoding="utf-8")
    (source / "CMakeLists.txt").write_text(
        """project(x C)
cmake_dependent_option(BUILD_TESTING "tests" ON "TRUE" OFF)
if(BUILD_TESTING)
  add_subdirectory(test)
endif()
add_library(x STATIC src/impl.c)
""",
        encoding="utf-8",
    )
    target = tmp_path / "agent"
    task = {
        "task_id": "x",
        "scenario": "windows_to_kylin",
        "build": {"command": "cmake -S . -B {build} -DBUILD_TESTING=ON"},
    }

    result = agent_view.copy_agent_view(source, target, task)
    cmake = (target / "CMakeLists.txt").read_text(encoding="utf-8")

    assert (target / "src" / "impl.c").exists()
    assert not (target / ".github").exists()
    assert not (target / "docs").exists()
    assert not (target / "test").exists()
    assert not (target / "README.md").exists()
    assert not (target / "ChangeLog").exists()
    assert not (target / "configure.ac").exists()
    assert "add_subdirectory(test)" not in cmake
    assert "BUILD_TESTING" not in cmake
    assert "add_subdirectory(test)" not in cmake
    assert "src/impl.c" in cmake
    assert ".github/ci.yml" in result["omitted"]


def test_kylin_judge_overlay_keeps_pristine_cmake(tmp_path):
    full = tmp_path / "full"
    agent = tmp_path / "agent"
    full.mkdir()
    agent.mkdir()
    pristine = "if(BUILD_TESTING)\n  add_subdirectory(test)\nendif()\n"
    sanitized = "add_library(x STATIC src/impl.c)\n"
    (full / "CMakeLists.txt").write_text(pristine, encoding="utf-8")
    (agent / "CMakeLists.txt").write_text(sanitized, encoding="utf-8")
    (agent / "src").mkdir()
    (agent / "src" / "impl.c").write_text("new\n", encoding="utf-8")
    task = {"task_id": "x", "scenario": "windows_to_kylin"}

    result = agent_view.copy_overlay(agent, full, task)

    assert (full / "CMakeLists.txt").read_text() == pristine
    assert (full / "src" / "impl.c").read_text() == "new\n"
    assert "CMakeLists.txt" in result["omitted"]


def test_positive_target_api_gate_requires_target(tmp_path):
    from migration_scenario_validation.shared.harness import api_removal

    source = tmp_path / "src"
    source.mkdir()
    (source / "impl.c").write_text("int f(void) { return 0; }\n", encoding="utf-8")
    miss = api_removal.scan(
        source_dirs=[str(source)],
        source_regex=r"\bvsip_[A-Za-z0-9_]+\b",
        positive=True,
    )
    assert miss["status"] == "fail"

    (source / "impl.c").write_text("int f(void) { return vsip_init(0); }\n", encoding="utf-8")
    hit = api_removal.scan(
        source_dirs=[str(source)],
        source_regex=r"\bvsip_[A-Za-z0-9_]+\b",
        positive=True,
    )
    assert hit["status"] == "pass"


def test_runner_target_api_gate_blocks_portable_fallback(tmp_path):
    task_root = tmp_path / "task"
    work = task_root / "src"
    work.mkdir(parents=True)
    # A full work tree is the task root for this direct source-only test.
    (task_root / "work").mkdir()
    (task_root / "work" / "src").mkdir()
    (task_root / "work" / "src" / "impl.c").write_text("int f(void) { return 0; }\n", encoding="utf-8")
    task = {
        "task_id": "target_gate_demo",
        "scenario": "ipp_to_vsipl",
        "level": "L1",
        "source": {"repo": "synthetic", "commit": "-", "license": "synthetic"},
        "target": {"api": "VSIPL"},
        "fit": "B",
        "spec": "migrate",
        "build": {"mode": "none", "command": ""},
        "hidden_tests": {"command": "true"},
        "gates": {
            "build": "none",
            "api_removal": "true",
            "target_api": {
                "source_dirs": ["src"],
                "source_regex": r"\bvsip_[A-Za-z0-9_]+\b",
            },
        },
    }
    import yaml
    (task_root / "task.yaml").write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")
    result = runner.run(
        str(task_root),
        work_dir=str(task_root / "work"),
        skip_build=True,
        skip_api=False,
    )
    assert result["status"] == "fail"
    assert result["target_api"] == "fail"

    (task_root / "work" / "src" / "impl.c").write_text(
        "int f(void) { return vsip_init(0); }\n", encoding="utf-8"
    )
    result = runner.run(
        str(task_root),
        work_dir=str(task_root / "work"),
        skip_build=True,
        skip_api=False,
    )
    assert result["status"] == "pass"
    assert result["target_api"] == "pass"
