import assert from "node:assert/strict";
import test from "node:test";

import { apply as source } from "../../source-scan/dist/index.js";
import { apply as signal } from "../../signal-analysis/dist/index.js";
import { apply as protocol } from "../../protocol-candidates/dist/index.js";
import { apply as build } from "../../component-build/dist/index.js";
import { apply as publish } from "../../library-publish/dist/index.js";
import { apply as retrieval } from "../../retrieval/dist/index.js";
import { apply as task } from "../../task-execution/dist/index.js";
import { apply as report } from "../../reporting/dist/index.js";
import { apply as orchestrator } from "../dist/index.js";
import { apply as ops } from "../../method-ops/dist/index.js";

function names(apply) {
  const registered = [];
  apply({ tools: { register: (tool) => registered.push(tool.name) } });
  return registered;
}

test("all stage plugins register their declared tools", () => {
  assert.deepEqual(names(source), ["component_source_scan"]);
  assert.deepEqual(names(signal), ["component_signal_prepare", "component_signal_embed"]);
  assert.deepEqual(names(protocol), ["component_protocol_build"]);
  assert.deepEqual(names(build), [
    "component_extract",
    "component_curate",
    "component_prepare_reviews",
    "component_review",
    "component_finalize_review",
  ]);
  assert.deepEqual(names(publish), ["component_publish_library"]);
  assert.deepEqual(names(retrieval), ["component_retrieval", "component_catalog", "component_validate_selection", "component_materialize_selection"]);
  assert.deepEqual(names(task), ["component_task"]);
  assert.deepEqual(names(report), ["component_report"]);
  assert.deepEqual(names(orchestrator), [
    "component_run_stage",
    "component_pipeline_run",
    "component_job_status",
    "component_job_cancel",
  ]);
  assert.deepEqual(names(ops), ["component_prepare_workspace", "component_dataset_adapter"]);
});
