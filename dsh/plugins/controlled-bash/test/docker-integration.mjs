import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { chmod, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { apply as controlledBashPlugin } from "../dist/index.js";


const enabled = process.env.COMPONENT_DSH_DOCKER_INTEGRATION === "1";
const image = process.env.COMPONENT_DSH_DOCKER_TEST_IMAGE
  || "task-guided-demo10/elastic-curator:1085-runtime";

function docker(...args) {
  return execFileSync("docker", args, { encoding: "utf8" }).trim();
}

test("controlled bash enforces the real Docker boundary", { skip: !enabled }, async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "component-dsh-plugin-"));
  const workspace = path.join(root, "workspace");
  const output = path.join(root, "output");
  const checker = path.join(root, "check_output.py");
  const validated = path.join(root, "validated_submission.json");
  const container = `component-dsh-plugin-${process.pid}-${Date.now()}`;
  await mkdir(workspace);
  await mkdir(output, { mode: 0o777 });
  await chmod(output, 0o777);
  await writeFile(path.join(workspace, "sentinel.txt"), "workspace-visible\n");
  await writeFile(
    checker,
    [
      "from pathlib import Path",
      "import sys",
      "if '--require-token' in sys.argv:",
      "    index = sys.argv.index('--require-token')",
      "    if sys.argv[index + 1] != 'retrieval':",
      "        print('Submission check failed: wrong checker token')",
      "        raise SystemExit(1)",
      "target = Path('/component-output/result.txt')",
      "if not target.is_file() or target.read_text().strip() != 'valid':",
      "    print('Submission check failed: result.txt must contain valid')",
      "    raise SystemExit(1)",
      "print('Submission files are valid.')",
      "",
    ].join("\n"),
  );

  try {
    docker(
      "run",
      "--detach",
      "--name",
      container,
      "--network",
      "none",
      "--read-only",
      "--tmpfs",
      "/tmp:rw,nosuid,nodev,size=64m,mode=1777",
      "--cap-drop",
      "ALL",
      "--security-opt",
      "no-new-privileges:true",
      "--volume",
      `${workspace}:/testbed:ro`,
      "--volume",
      `${output}:/component-output:rw`,
      "--volume",
      `${checker}:/component-tools/check_output.py:ro`,
      "--entrypoint",
      "",
      image,
      "sleep",
      "infinity",
    );
    assert.equal(docker("inspect", container, "--format", "{{.HostConfig.NetworkMode}}"), "none");

    process.env.HOST_ONLY_SECRET = "must-not-enter-container";
    process.env.COMPONENT_DSH_CONTAINER_NAME = container;
    process.env.COMPONENT_DSH_ALLOWED_CWDS = JSON.stringify(["/testbed"]);
    process.env.COMPONENT_DSH_COMMAND_TIMEOUT = "30";
    process.env.COMPONENT_DSH_SUBMISSION_MODE = "files";
    process.env.COMPONENT_DSH_SUBMISSION_ROLE = "extraction";
    process.env.COMPONENT_DSH_VALIDATED_SUBMISSION_PATH = validated;
    process.env.COMPONENT_DSH_CHECKER_COMMAND_JSON = JSON.stringify([
      "python",
      "/component-tools/check_output.py",
      "--require-token",
      "retrieval",
    ]);
    let tool;
    controlledBashPlugin({ tools: { register(value) { tool = value; } } });
    assert.ok(tool);

    const execution = { concluded: false, concludeTurn() { this.concluded = true; } };
    const inspect = await tool.execute(
      { command: "pwd; cat sentinel.txt; env", cwd: "/testbed", timeout_seconds: 10 },
      execution,
    );
    assert.equal(inspect.exit_code, 0);
    assert.match(inspect.output, /\/testbed/);
    assert.match(inspect.output, /workspace-visible/);
    assert.doesNotMatch(inspect.output, /HOST_ONLY_SECRET|must-not-enter-container/);
    assert.equal(execution.concluded, false);
    await assert.rejects(
      tool.execute(
        { command: "pwd", cwd: "/testbed/../etc", timeout_seconds: 10 },
        execution,
      ),
      /outside the allowed/,
    );

    const rejected = await tool.execute(
      {
        command: "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n'",
        cwd: "/testbed",
        timeout_seconds: 10,
      },
      execution,
    );
    assert.notEqual(rejected.exit_code, 0);
    assert.match(rejected.output, /Submission rejected/);
    assert.equal(execution.concluded, false);

    const write = await tool.execute(
      { command: "printf valid > /component-output/result.txt", cwd: "/testbed", timeout_seconds: 10 },
      execution,
    );
    assert.equal(write.exit_code, 0);
    const submitted = await tool.execute(
      {
        command: "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n'",
        cwd: "/testbed",
        timeout_seconds: 10,
      },
      execution,
    );
    assert.equal(submitted.exit_code, 0);
    assert.equal(execution.concluded, true);
    assert.match(submitted.output, /"transport":"files"/);
    const record = JSON.parse(await readFile(validated, "utf8"));
    assert.equal(record.validated, true);
    assert.equal(record.container_name, container);
    assert.equal(record.role, "extraction");

    execution.concluded = false;
    process.env.COMPONENT_DSH_SUBMISSION_MODE = "patch";
    process.env.COMPONENT_DSH_SUBMISSION_ROLE = "task";
    const patchSubmitted = await tool.execute(
      {
        command: "printf 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\\n'",
        cwd: "/testbed",
        timeout_seconds: 10,
      },
      execution,
    );
    assert.equal(patchSubmitted.exit_code, 0);
    assert.equal(execution.concluded, true);
    assert.match(patchSubmitted.output, /"transport":"patch"/);
    const patchRecord = JSON.parse(await readFile(validated, "utf8"));
    assert.equal(patchRecord.transport, "patch");
    assert.equal(patchRecord.role, "task");
  } finally {
    try {
      docker("rm", "--force", container);
    } catch {
      // The container may not have been created if setup failed.
    }
    await rm(root, { recursive: true, force: true });
  }
});
