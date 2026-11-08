"""Verify that the distributed official evaluator can load its parser dependencies."""

from pathlib import Path
import subprocess
import sys


def test_packaged_official_evaluator_imports_and_parses_real_statuses(tmp_path):
    runtime = Path(__file__).resolve().parents[2] / "src/component_method/task_execution"
    script = """
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

runtime = Path(sys.argv[1])
sys.modules['common'] = SimpleNamespace(
    RUNTIME_ROOT=runtime, OUT=Path(sys.argv[2]),
    evaluation_adjustments=lambda: {}, read=lambda path: {}, write=lambda path, value: None,
)
spec = importlib.util.spec_from_file_location('packaged_evaluation', runtime / 'core/evaluation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
helper = module.evaluator()
parser = helper.get_parser('parse_log_pytest')
assert parser('PASSED unit.py::one\\nFAILED unit.py::two - assertion\\nSKIPPED unit.py::three\\nERROR unit.py::four') == {
    'unit.py::one': 'PASSED', 'unit.py::two': 'FAILED',
    'unit.py::three': 'SKIPPED', 'unit.py::four': 'ERROR',
}
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(runtime), str(tmp_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
