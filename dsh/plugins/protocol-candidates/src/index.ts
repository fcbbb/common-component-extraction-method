import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-protocol-candidates";
export const inject = ["tools"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_protocol_build",
      description: "Build protocol-aware candidates from embeddings.",
      method: "protocol_build",
      parameters: {"run_id": {"type": "string", "required": true}, "tasks": {"type": "array", "items": {"type": "string"}}, "resume": {"type": "boolean"}, "include_reserve": {"type": "boolean"}, "regenerate_frozen_candidates": {"type": "boolean"}},
    },
  ]);
}
