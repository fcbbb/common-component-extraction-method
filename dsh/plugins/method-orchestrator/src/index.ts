import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-orchestrator";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_run_stage",
      description: "Run one registered method stage.",
      method: "run_stage",
      parameters: {"run_id": {"type": "string", "required": true}, "stage": {"type": "string", "required": true}, "task_id": {"type": "string"}, "workers": {"type": "integer"}, "resume": {"type": "boolean"}},
    },
    {
      name: "component_pipeline_run",
      job: true,
      description: "Start the full run_batch pipeline as a job.",
      method: "pipeline",
      parameters: {"run_id": {"type": "string", "required": true}, "tasks": {"type": "array", "items": {"type": "string"}}, "resume": {"type": "boolean"}, "task_workers": {"type": "integer"}, "extraction_workers": {"type": "integer"}, "review_workers": {"type": "integer"}},
    },
    {
      name: "component_job_status",
      description: "Read one method job status.",
      method: "job_status",
      parameters: {"job_id": {"type": "string", "required": true}},
    },
    {
      name: "component_job_cancel",
      description: "Cancel one method job.",
      method: "job_cancel",
      parameters: {"job_id": {"type": "string", "required": true}},
    },
  ]);
}
