import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-retrieval";
// Retrieval runs as a background job, so `jobs` is a required service.
export const inject = ["tools", "jobs"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_retrieval",
      job: true,
      description: "Run retrieval for a registered task.",
      method: "retrieval",
      parameters: {"run_id": {"type": "string", "required": true}, "task_id": {"type": "string", "required": true}},
    },
    {
      name: "component_catalog",
      description: "Read the controller-mounted component catalog.",
      method: "catalog",
      parameters: {},
    },
    {
      name: "component_validate_selection",
      description: "Validate the current coverage and selection files.",
      method: "validate_selection",
      parameters: {},
    },
    {
      name: "component_materialize_selection",
      description: "Materialize the validated component selection.",
      method: "materialize_selection",
      parameters: {},
    },
  ]);
}
