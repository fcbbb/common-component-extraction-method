"""The shared location of extracted artifacts inside the task repository."""

from pathlib import Path
import re


COMPONENT_DIRECTORY = "/testbed/component_bundle"
TASK_RUNTIME_ACTIVATION = (
    "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed"
)


def neutral_agent_text(text: str) -> str:
    """Normalize generated instructions, including saved prompt overrides."""
    for old, new in (
        ("/testbed/.components", COMPONENT_DIRECTORY),
        ("/testbed/.featurebench_components", COMPONENT_DIRECTORY),
        ("/opt/featurebench/community-components", COMPONENT_DIRECTORY),
        ("/opt/components", COMPONENT_DIRECTORY),
        ("/tmp/featurebench_component_task.txt", "/tmp/component_task.txt"),
        ("/tmp/featurebench-component-discovery", "/tmp/component-discovery"),
    ):
        text = text.replace(old, new)
    return re.sub("featurebench", "component-system", text, flags=re.IGNORECASE)


def prepare_component_mount(repo_root: Path) -> None:
    """Create an empty mount point without changing original repository files."""
    target = repo_root.resolve() / "component_bundle"
    if target.is_symlink():
        raise ValueError("component mount point must not be a symlink")
    target.mkdir(exist_ok=True)
