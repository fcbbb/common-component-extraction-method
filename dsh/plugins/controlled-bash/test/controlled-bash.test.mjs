import assert from "node:assert/strict";
import test from "node:test";

import {
  allowedCwd,
  canonicalResult,
  decodeDockerStream,
  containsCompletionMarker,
  cwdOrFallback,
  firstEffectiveLine,
  submissionCheckerCommand,
} from "../dist/index.js";


test("cwd must stay inside the controller allowlist", () => {
  process.env.COMPONENT_DSH_ALLOWED_CWDS = JSON.stringify(["/testbed"]);
  assert.equal(allowedCwd("/testbed"), "/testbed");
  assert.equal(allowedCwd("/testbed/src/"), "/testbed/src");
  assert.throws(() => allowedCwd("/testbed-other"), /outside the allowed/);
  assert.throws(() => allowedCwd("/testbed/../etc"), /outside the allowed/);
  assert.throws(() => allowedCwd("testbed"), /absolute container path/);
});

test("completion marker is detected as a standalone output line", () => {
  assert.equal(
    firstEffectiveLine(Buffer.from("\n COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT \nextra\n")),
    "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
  );
  assert.equal(containsCompletionMarker(Buffer.from("ordinary\nCOMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n")), true);
  assert.equal(containsCompletionMarker(Buffer.from("ordinary output\n")), false);
});

test("large output keeps its head and tail and reports original bytes", () => {
  process.env.COMPONENT_DSH_OUTPUT_LIMIT = "2000";
  const output = Buffer.from(`HEAD${"x".repeat(3000)}TAIL`);
  const result = canonicalResult({ exitCode: 0, output, durationMs: 12 });
  assert.equal(result.output_bytes, output.byteLength);
  assert.equal(result.truncated, true);
  assert.match(result.output, /^HEAD/);
  assert.match(result.output, /TAIL$/);
  assert.match(result.output, /output truncated/);
});

test("Docker multiplexed stdout and stderr frames are decoded", () => {
  const frame = (stream, text) => {
    const body = Buffer.from(text);
    const header = Buffer.alloc(8);
    header[0] = stream;
    header.writeUInt32BE(body.byteLength, 4);
    return Buffer.concat([header, body]);
  };
  assert.equal(
    decodeDockerStream(Buffer.concat([frame(1, "stdout"), frame(2, "stderr")])).toString(),
    "stdoutstderr",
  );
});

test("a controller-supplied checker command is parsed and shell quoted", () => {
  process.env.COMPONENT_DSH_CHECKER_COMMAND_JSON = JSON.stringify([
    "python",
    "/retrieval-tools/check_selection.py",
    "--task-id",
    "task with spaces",
    "--submit",
  ]);
  assert.equal(
    submissionCheckerCommand("retrieval"),
    "'python' '/retrieval-tools/check_selection.py' '--task-id' 'task with spaces' '--submit'",
  );
  delete process.env.COMPONENT_DSH_CHECKER_COMMAND_JSON;
});


test("invalid cwd can fall back explicitly to the configured container cwd", () => {
  process.env.COMPONENT_DSH_ALLOWED_CWDS = JSON.stringify(["/testbed"]);
  process.env.COMPONENT_DSH_DEFAULT_CWD = "/testbed";
  assert.equal(cwdOrFallback("/host/workspace/dsh"), "/testbed");
  assert.equal(cwdOrFallback("/testbed/component_bundle"), "/testbed/component_bundle");
  delete process.env.COMPONENT_DSH_DEFAULT_CWD;
  assert.throws(() => cwdOrFallback("/host/workspace/dsh"), /outside the allowed/);
});
