import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-component-build";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_extract",
      job: true,
      description: "Run task-blind component extraction.",
      method: "extract",
      parameters: {"run_id": {"type": "string", "required": true}, "task_id": {"type": "string"}, "workers": {"type": "integer"}, "resume": {"type": "boolean"}},
    },
    {
      name: "component_curate",
      description: "Curate extraction output into frozen components.",
      method: "curate",
      parameters: {"run_id": {"type": "string", "required": true}},
    },
    {
      name: "component_prepare_reviews",
      description: "Prepare review inputs.",
      method: "prepare_reviews",
      parameters: {"run_id": {"type": "string", "required": true}},
    },
    {
      name: "component_review",
      job: true,
      description: "Run component review and smoke validation.",
      method: "review",
      parameters: {"run_id": {"type": "string", "required": true}, "workers": {"type": "integer"}, "resume": {"type": "boolean"}},
    },
    {
      name: "component_finalize_review",
      description: "Finalize a single review without a second model review.",
      method: "finalize_review",
      parameters: {"run_id": {"type": "string", "required": true}},
    },
  ]);
}
