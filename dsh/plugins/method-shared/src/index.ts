import { spawn } from "node:child_process";
import { defineTool } from "@deepseek-ai/dsh-tools";

export interface KernelToolSpec {
  name: string;
  description: string;
  method: string;
  parameters?: Record<string, unknown>;
  job?: boolean;
  render?: (value: Record<string, unknown>) => string;
}

export interface KernelRunOptions {
  job?: boolean;
  timeoutMs?: number;
}

function kernelEnvironment(): NodeJS.ProcessEnv {
  const environment: NodeJS.ProcessEnv = {};
  for (const name of [
    "PATH",
    "HOME",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "MODEL_NAME",
    "OPENAI_API_BASE",
    "OPENAI_API_KEY",
  ]) {
    if (process.env[name]) environment[name] = process.env[name];
  }
  for (const [name, value] of Object.entries(process.env)) {
    if (name.startsWith("COMPONENT_DSH_") && value !== undefined) {
      environment[name] = value;
    }
  }
  const root = process.env.COMPONENT_DSH_METHOD_ROOT;
  if (root) {
    const parts = [`${root}/src`];
    if (environment.PYTHONPATH) parts.push(environment.PYTHONPATH);
    environment.PYTHONPATH = parts.join(":");
  }
  return environment;
}

export function runKernel(
  method: string,
  payload: Record<string, unknown>,
  options: KernelRunOptions = {},
): Promise<Record<string, unknown>> {
  const python = process.env.COMPONENT_DSH_PYTHON_BIN || "python3";
  const root = process.env.COMPONENT_DSH_METHOD_ROOT;
  if (!root) {
    return Promise.reject(new Error("COMPONENT_DSH_METHOD_ROOT is not configured"));
  }
  if (!/^[a-z][a-z0-9_]*$/.test(method)) {
    return Promise.reject(new Error(`invalid kernel method: ${method}`));
  }
  const args = ["-m", "component_method.dsh_kernel", method];
  if (options.job) args.push("--job");

  return new Promise((resolve, reject) => {
    const child = spawn(python, args, {
      cwd: root,
      env: kernelEnvironment(),
      stdio: ["pipe", "pipe", "pipe"],
      shell: false,
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      reject(new Error(`kernel method timed out: ${method}`));
    }, options.timeoutMs ?? 60_000);

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => { stdout += chunk; });
    child.stderr.on("data", (chunk: string) => { stderr += chunk; });
    child.on("error", (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (code !== 0 && !stdout.trim()) {
        reject(new Error(stderr.trim() || `kernel exited with ${code}`));
        return;
      }
      try {
        const parsed: unknown = JSON.parse(stdout);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          reject(new Error("kernel returned a non-object JSON value"));
          return;
        }
        resolve(parsed as Record<string, unknown>);
      } catch (error) {
        reject(new Error(`kernel returned invalid JSON: ${String(error)}\n${stdout.slice(0, 2000)}`));
      }
    });
    child.stdin.end(JSON.stringify(payload));
  });
}

export function kernelTool(spec: KernelToolSpec): any {
  return defineTool({
    name: spec.name,
    description: spec.description,
    parameters: (spec.parameters ?? {}) as any,
    output: {
      schema: {
        type: "object",
        additionalProperties: true,
        properties: {
          ok: { type: "boolean", required: true },
          method: { type: "string" },
          job_id: { type: "string" },
          exit_code: { type: "integer" },
          stdout: { type: "string" },
          stderr: { type: "string" },
          error: { type: "string" },
          diagnostics: { type: "array", items: { type: "string" } },
        },
      },
      render: (_args: unknown, value: any) => [{
        type: "text",
        text: spec.render
          ? spec.render(value)
          : (typeof value.summary === "string"
            ? value.summary
            : JSON.stringify(value).slice(0, 4000)),
      }],
    },
    async execute(args: Record<string, unknown>) {
      return (await runKernel(spec.method, args ?? {}, { job: spec.job })) as any;
    },
  });
}

export function registerTools(ctx: any, specs: KernelToolSpec[]): void {
  for (const spec of specs) {
    ctx.tools.register(kernelTool(spec));
  }
}
