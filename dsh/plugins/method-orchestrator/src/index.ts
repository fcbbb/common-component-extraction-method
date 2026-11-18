import { BACKGROUND_STAGES, registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-orchestrator";
// Long stages run through the built-in job runtime, so `jobs` is a hard
// dependency: Cordis refuses to load this plugin in a profile that does not
// mount `@deepseek-ai/dsh-tool-jobs`.
export const inject = ["tools", "jobs"];

/** Every stage the single entry accepts.  `finalize_review`, `task` and
 * `report` are deliberately absent: the normal pipeline publishes reviewed
 * components, and the migration workspace runs the task in the main agent's
 * session rather than as a method stage. */
export const STAGES = [
  "source_scan",
  "extract",
  "curate",
  "prepare_reviews",
  "review",
  "publish_library",
  "retrieval",
  "catalog",
  "validate_selection",
  "materialize_selection",
];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_run_stage",
      description:
        "Run one component-method stage. This is the only stage entry: pass stage "
        + "= source_scan | extract | curate | prepare_reviews | review | "
        + "publish_library | retrieval | catalog | validate_selection | "
        + "materialize_selection. Long stages (extract, review, retrieval) start as a "
        + "background job and return a job_id with status 'running'; wait for the "
        + "completion notice or call job_output. Every result carries status, "
        + "summary, artifacts and error_code.",
      method: "run_stage",
      job: (args: Record<string, unknown>) => BACKGROUND_STAGES.has(String(args.stage)),
      parameters: {
        "run_id": {"type": "string", "required": true},
        "stage": {"type": "string", "required": true, "enum": STAGES},
        "task_id": {"type": "string"},
        "workers": {"type": "integer"},
        "resume": {"type": "boolean"},
      },
    },
  ]);
}