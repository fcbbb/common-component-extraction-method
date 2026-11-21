import { spawn, type ChildProcess } from "node:child_process";
import { defineTool } from "@deepseek-ai/dsh-tools";

/**
 * Default budget for a synchronous kernel tool call.  Synchronous stages parse
 * whole repositories, which routinely exceeds a minute on large trees; the
 * previous hard-coded 60s killed long source scans and left the workflow agent
 * retrying a stage that was working.
 */
export const DEFAULT_KERNEL_TIMEOUT_MS = 600_000;

/** Stages that are long enough to belong in the background-job runtime. */
export const BACKGROUND_STAGES = new Set([
  "build",
  "audit",
  "deliver",
  "pipeline",
  "extract",
  "retrieval",
  "review",
  "task",
]);

/**
 * One method tool.  ``job`` is either a fixed choice or a per-call predicate,
 * so ``run_stage`` can run a cheap stage inline and hand a long stage to
 * ``ctx.jobs`` without splitting the tool surface.
 */
export interface KernelToolSpec {
  name: string;
  description: string;
  method: string;
  parameters?: Record<string, unknown>;
  job?: boolean | ((args: Record<string, unknown>) => boolean);
  /**
   * Wall-clock budget for the kernel process.  Synchronous stages (source
   * scan, curate, publish) parse whole repositories and can take minutes on
   * large trees, so the default is deliberately generous.  Background stages
   * leave it unset: the kernel itself bounds the stage subprocess and a
   * background job must not be killed by the caller's patience.
   */
  timeoutMs?: number;
  /** One-line label shown by ``job_list`` for a background stage. */
  jobLabel?: (args: Record<string, unknown>) => string;
  render?: (value: Record<string, unknown>) => string;
}

export interface KernelRunOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
  onStderr?: (text: string) => void;
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

export interface KernelProcess {
  child: ChildProcess;
  /** Parsed kernel JSON, or a rejection when the process died without one. */
  done: Promise<Record<string, unknown>>;
}

/**
 * Start one kernel process.  The caller either awaits ``done`` (synchronous
 * tools) or owns the job lifecycle and settles it from ``done`` (background
 * stages).
 */
export function startKernel(
  method: string,
  payload: Record<string, unknown>,
  options: KernelRunOptions = {},
): KernelProcess {
  const python = process.env.COMPONENT_DSH_PYTHON_BIN || "python3";
  const root = process.env.COMPONENT_DSH_METHOD_ROOT;
  if (!root) {
    throw new Error("COMPONENT_DSH_METHOD_ROOT is not configured");
  }
  if (!/^[a-z][a-z0-9_]*$/.test(method)) {
    throw new Error(`invalid kernel method: ${method}`);
  }
  const child = spawn(python, ["-m", "component_method.dsh_kernel", method], {
    cwd: root,
    env: kernelEnvironment(),
    stdio: ["pipe", "pipe", "pipe"],
    shell: false,
  });
  let stdout = "";
  let stderr = "";
  let settled = false;
  let timer: NodeJS.Timeout | undefined;

  const done = new Promise<Record<string, unknown>>((resolve, reject) => {
    const finish = (settle: () => void): void => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      settle();
    };
    if (options.timeoutMs && options.timeoutMs > 0) {
      timer = setTimeout(() => {
        child.kill("SIGKILL");
        finish(() => reject(new Error(`kernel method timed out: ${method}`)));
      }, options.timeoutMs);
      timer.unref?.();
    }
    if (options.signal) {
      const kill = () => child.kill("SIGKILL");
      if (options.signal.aborted) kill();
      else options.signal.addEventListener("abort", kill, { once: true });
    }
    child.stdout?.setEncoding("utf8");
    child.stderr?.setEncoding("utf8");
    child.stdout?.on("data", (chunk: string) => { stdout += chunk; });
    child.stderr?.on("data", (chunk: string) => {
      stderr += chunk;
      options.onStderr?.(chunk);
    });
    child.on("error", (error) => {
      finish(() => reject(error));
    });
    child.on("close", (code) => {
      finish(() => {
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
    });
  });
  // A rejected ``done`` is reported by every caller; keep an unawaited one
  // from surfacing as an unhandled rejection in the plugin process.
  done.catch(() => {});
  try {
    child.stdin?.end(JSON.stringify(payload));
  } catch (error) {
    child.kill("SIGKILL");
  }
  return { child, done };
}

export function runKernel(
  method: string,
  payload: Record<string, unknown>,
  options: KernelRunOptions = {},
): Promise<Record<string, unknown>> {
  return startKernel(method, payload, options).done;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The one result sheet: ``status / summary / artifacts / error_code``.
 *
 * ``ok`` stays as a convenience for older prompt text and tests, but every
 * caller can now branch on ``status`` alone.
 */
export function normalizeEnvelope(value: Record<string, unknown>): Record<string, unknown> {
  const ok = value.ok !== false;
  const rawStatus = typeof value.status === "string"
    ? value.status
    : (ok ? "succeeded" : "failed");
  // Job states and stage outcomes share one vocabulary at the tool boundary.
  const status = rawStatus === "missing" || rawStatus === "failed"
    ? "failed"
    : rawStatus === "cancelled" || rawStatus === "killed"
      ? "cancelled"
      : rawStatus === "succeeded" || rawStatus === "completed"
        ? "succeeded"
        : rawStatus === "running" || rawStatus === "stopping"
          ? "running"
          : rawStatus;
  const envelope: Record<string, unknown> = {
    ...value,
    ok: status === "succeeded" || status === "running",
    status,
    summary: isRecord(value.summary) ? value.summary : {},
    artifacts: isRecord(value.artifacts) ? value.artifacts : {},
    error_code: value.error_code ?? (status === "succeeded" || status === "running" ? null : "STAGE_FAILED"),
  };
  return envelope;
}

function runningEnvelope(
  spec: KernelToolSpec,
  payload: Record<string, unknown>,
  jobId: string,
): Record<string, unknown> {
  const envelope: Record<string, unknown> = {
    ok: true,
    status: "running",
    method: spec.method,
    job_id: jobId,
    summary: {},
    artifacts: {},
    error_code: null,
  };
  if (typeof payload.stage === "string") envelope.stage = payload.stage;
  return envelope;
}

function defaultJobLabel(spec: KernelToolSpec, payload: Record<string, unknown>): string {
  const stage = typeof payload.stage === "string" ? payload.stage : spec.method;
  const run = typeof payload.run_id === "string" ? payload.run_id : "";
  return run ? `component stage ${stage} (${run})` : `component stage ${stage}`;
}

function outcomeDetail(envelope: Record<string, unknown>): string | undefined {
  if (typeof envelope.error === "string" && envelope.error) {
    return envelope.error.slice(0, 400);
  }
  if (typeof envelope.status === "string") return `status: ${envelope.status}`;
  return undefined;
}

/** Start one stage through the built-in job runtime and return its id at once. */
function startStageJob(
  ctx: any,
  spec: KernelToolSpec,
  payload: Record<string, unknown>,
  exec: any,
): Record<string, unknown> {
  // Every plugin that registers a job-backed tool declares `jobs` in its own
// `inject`, so this is a required service rather than an optional lookup.
  const jobs = ctx?.jobs;
  if (!jobs || typeof jobs.start !== "function") {
    throw new Error(
      "background stages need the built-in job runtime: load '@deepseek-ai/dsh-tool-jobs' in this profile",
    );
  }
  const owner = exec?.agent?.id;
  if (!owner) {
    throw new Error("background stages need an owning agent session");
  }
  const state: { child: ChildProcess | null; cancelRequested: boolean } = {
    child: null,
    cancelRequested: false,
  };
  const jobId: string = jobs.start({
    kind: "method-stage",
    label: spec.jobLabel ? spec.jobLabel(payload) : defaultJobLabel(spec, payload),
    owner,
    toolCall: exec ? { callId: exec.callId, rootCallId: exec.rootCallId } : undefined,
    // Left unset on purpose: the kernel bounds the stage itself, and a
    // background job must survive the turn that started it.
    outputLimitBytes: 16_384,
    run(handle: any) {
      const kernel = startKernel(spec.method, payload, {
        signal: undefined,
        onStderr: (text) => handle.append(text, { channel: "stderr" }),
      });
      state.child = kernel.child;
      handle.updateProgress(`${spec.method} running`);
      const done = kernel.done.then(
        (value) => {
          const envelope = normalizeEnvelope(value);
          handle.updateProgress(`${spec.method} finished`);
          return {
            status: state.cancelRequested || envelope.status === "cancelled"
              ? "killed"
              : (envelope.status === "succeeded" ? "completed" : "failed"),
            detail: outcomeDetail(envelope),
            result: JSON.stringify(envelope),
          };
        },
        (error) => {
          handle.updateProgress(`${spec.method} failed`);
          return {
            status: state.cancelRequested ? "killed" : "failed",
            detail: String((error as Error)?.message ?? error).slice(0, 400),
          };
        },
      );
      return {
        cancel() {
          state.cancelRequested = true;
          const child = state.child;
          if (!child || child.exitCode !== null) return;
          child.kill("SIGTERM");
          const timer = setTimeout(() => {
            if (child.exitCode === null) child.kill("SIGKILL");
          }, 5_000);
          timer.unref?.();
        },
        done,
      };
    },
  });
  return runningEnvelope(spec, payload, jobId);
}

function renderEnvelope(value: Record<string, unknown>): string {
  if (value.status === "running" && typeof value.job_id === "string") {
    const stage = typeof value.stage === "string" ? value.stage : value.method;
    return [
      `started ${String(stage)} as job ${value.job_id} (status: running).`,
      `Wait for the completion notice, or call job_output with {"job_id": "${value.job_id}", "wait": true, "timeout_ms": 600000}.`,
      "The finished job reports status, summary, artifacts and error_code.",
    ].join("\n");
  }
  const lines = [`status: ${String(value.status ?? (value.ok ? "succeeded" : "failed"))}`];
  if (typeof value.stage === "string") lines.push(`stage: ${value.stage}`);
  if (isRecord(value.summary) && Object.keys(value.summary).length > 0) {
    lines.push(`summary: ${JSON.stringify(value.summary)}`);
  }
  if (isRecord(value.artifacts) && Object.keys(value.artifacts).length > 0) {
    lines.push(`artifacts: ${JSON.stringify(value.artifacts)}`);
  }
  if (value.error_code) lines.push(`error_code: ${String(value.error_code)}`);
  if (typeof value.error === "string" && value.error) lines.push(`error: ${value.error}`);
  const text = lines.join("\n");
  return text.length > 6000 ? `${text.slice(0, 6000)}\n…` : text;
}

export function kernelTool(spec: KernelToolSpec, ctx?: any): any {
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
          status: { type: "string" },
          stage: { type: "string" },
          method: { type: "string" },
          job_id: { type: "string" },
          // A running job has no exit code yet; the kernel reports null.
          exit_code: { oneOf: [{ type: "integer" }, { type: "null" }] },
          summary: { type: "object", additionalProperties: true },
          artifacts: { type: "object", additionalProperties: true },
          error_code: { oneOf: [{ type: "string" }, { type: "null" }] },
          stdout: { type: "string" },
          stderr: { type: "string" },
          error: { type: "string" },
          diagnostics: { type: "array", items: { type: "string" } },
        },
      },
      render: (_args: unknown, value: any) => [{
        type: "text",
        text: spec.render ? spec.render(value) : renderEnvelope(value),
      }],
    },
    async execute(args: Record<string, unknown>, exec?: any) {
      const payload = args ?? {};
      const wantsJob = typeof spec.job === "function" ? spec.job(payload) : spec.job === true;
      if (wantsJob) {
        if (!ctx) {
          throw new Error("background stages need the plugin context");
        }
        return startStageJob(ctx, spec, payload, exec) as any;
      }
      const value = await runKernel(spec.method, payload, {
        timeoutMs: spec.timeoutMs ?? DEFAULT_KERNEL_TIMEOUT_MS,
        signal: exec?.signal,
      });
      return normalizeEnvelope(value) as any;
    },
  });
}

export function registerTools(ctx: any, specs: KernelToolSpec[]): void {
  for (const spec of specs) {
    ctx.tools.register(kernelTool(spec, ctx));
  }
}