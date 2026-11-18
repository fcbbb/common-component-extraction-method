import { registerTools } from "@component-method/dsh-method-shared";

export const name = "component-method-signal-analysis";
// Embedding-corpus preparation runs as a background job, so `jobs` is a
// required service.
export const inject = ["tools", "jobs"];

export function apply(ctx: any): void {
  registerTools(ctx, [
    {
      name: "component_signal_prepare",
      description: "Prepare the embedding corpus for a registered run.",
      method: "signal_prepare",
      parameters: {"run_id": {"type": "string", "required": true}, "tasks": {"type": "array", "items": {"type": "string"}}},
    },
    {
      name: "component_signal_embed",
      job: true,
      description: "Start or run the embedding computation.",
      method: "signal_embed",
      parameters: {"run_id": {"type": "string", "required": true}, "device": {"type": "string", "enum": ["cuda", "cpu"]}, "batch_size": {"type": "integer"}, "chunk_size": {"type": "integer"}, "cpu_fallback_chars": {"type": "integer"}, "resume": {"type": "boolean"}},
    },
  ]);
}
