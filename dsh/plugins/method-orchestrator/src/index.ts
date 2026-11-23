import { BACKGROUND_STAGES, registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-orchestrator";
// Long stages run through the built-in job runtime, so `jobs` is a hard
// dependency: Cordis refuses to load this plugin in a profile that does not
// mount `@deepseek-ai/dsh-tool-jobs`.
export const inject = ["tools", "jobs"];

/** The six atomic blocks the single entry accepts.  Retired step names
 * (`extract`, `curate`, `review` …) still resolve inside the kernel, but the
 * model should select blocks; each block checks its own prerequisites.
 * `validate_selection` / `materialize_selection` now run inside `retrieval`,
 * and `report` / `catalog` stay callable through the kernel for batch and
 * operator clients; none of these are offered to the method agent. */
export const STAGES = [
  "prepare",
  "build",
  "audit",
  "publish",
  "retrieval",
  "task",
  "deliver",
];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_run_stage",
      description:
        "Run one atomic component-method block. This is the only stage entry: pass stage "
        + "= prepare | build | audit | publish | retrieval | task. Blocks merge former "
        + "steps: prepare=scan/packets, build=extract+curate+freeze, audit=review+finalize, "
        + "publish=library, retrieval=select+validate+materialize-bundle, task=execute. "
        + "The compatibility group deliver expands to retrieval+task. The kernel checks dependencies before it "
        + "runs anything: a missing input returns STAGE_INPUT_MISSING and a stage the "
        + "workspace forbids (task/report in migration) returns STAGE_UNSUPPORTED. "
        + "Long blocks (build, audit, retrieval, task) start as a background job and "
        + "return a job_id with status 'running'; wait for the completion notice or "
        + "call job_output. Every result carries status, summary, artifacts and "
        + "error_code.",
      method: "run_stage",
      job: (args: Record<string, unknown>) => BACKGROUND_STAGES.has(String(args.stage)),
      parameters: {
        "run_id": {"type": "string", "required": true},
        "stage": {"type": "string", "required": true, "enum": STAGES},
        "task_id": {"type": "string"},
        "workers": {"type": "integer"},
        "resume": {"type": "boolean"},
        "publish_mode": {"type": "string", "enum": ["reviewed", "unreviewed", "migration_direct"]},
      },
    },
  ]);
}