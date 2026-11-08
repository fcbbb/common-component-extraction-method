# Multilanguage Implementation Status

Updated: 2026-11-08. Design: [multilanguage_refactoring_plan.md](multilanguage_refactoring_plan.md).

The artifact-v2 pipeline implements scanning, signals, profiles, language-partitioned
candidates, multi-file extraction, review, bounded repair, isolated execution,
publication, retrieval selection and task environment delivery for Python, C++
and Java. Historical Python commands, imports and artifact formats remain supported.
The historical 20-task results have not been rerun or relabeled as multilingual results.

## Implemented Boundaries

| Area | Implementation |
| --- | --- |
| Contracts | Versioned source units, canonical unit keys, profiles, artifacts, entrypoints, smoke cases, observations, backend identities and task environments |
| Configuration | `languages`, legacy `language`, implicit Python default; deterministic ownership and include/exclude globs; explicit missing/conflicting backend errors |
| Source and signals | Backend-owned parsing, lexical normalization, structural tokens, ancestry and profiles; common ANN, graph and protocol algorithms |
| Candidates | One graph per language/backend; canonical references; deterministic merged packets; no cross-language candidate merging |
| Artifact submission | Multiple source/header/data files; declared qualified entrypoints and overload signatures; standalone file-based checker; v1 Python compatibility |
| Review and repair | Backend instructions, original source citations, exact member boundaries, eight-field protocol review, dependency accounting, frozen declarations and changed-line limits |
| Execution | Pinned local image IDs; offline Docker; read-only repository/artifact/driver mounts; process, memory and CPU limits; separate build directory |
| Evidence | Python interpreter frame events; C++ compiler function instrumentation and linkage symbols; Java JDK method-entry events |
| Publication | Schema-8 libraries, complete file digests, original source/backend provenance, per-entrypoint validation status, atomic publication |
| Retrieval and tasks | Language-preserving catalogs and selected bundles; backend environment variables; original task image remains the formal evaluator image |
| Freezing and caches | Backend/parser/configuration identities and source hashes in new manifests; changed backends invalidate reuse; legacy frozen inputs remain readable |

The new workflow and validation controller contain no language-specific dispatch
branches. Python syntax, grounding, legacy runtime, repair and publication logic
live in `languages/python/`; old module paths remain compatibility imports.
The task-guided historical Python component construction route remains a legacy
route. New multilanguage extraction uses `workflow.multilanguage` and
`component_build.pipeline` rather than silently changing that experiment.

## Backends and Limits

| Backend | Parser | Runtime requirements | Supported execution evidence |
| --- | --- | --- | --- |
| `python@1` | Python stdlib AST | Image with Python and component dependencies | Actual entrypoint frame calls, including async smoke functions |
| `cpp@1` | libclang 18.1.1 | Image with Python controller, GNU C++ compiler and `nm` | Actual calls to exact compiler linkage symbols; separate headers and source files; overloads |
| `java@1` | tree-sitter 0.25.2 / tree-sitter-java 0.23.5 | Image with Python controller and full JDK with `jdk.jdi` | Actual method-entry events with argument types; multi-file package compilation; overloads |

C++ compilation databases supply a restricted projection of include paths,
defines, undefines, language standards and parser targets. Commands are parsed
as data and never executed on the host. Runtime compilation uses fixed argv
commands, remaps repository paths to the read-only `/repository` mount, and
records actual commands, compiler version, target and image ID. Cross-target
execution, arbitrary compiler/linker flags, external build scripts, and template
entrypoints without concrete linkage symbols require additional backend support.
When database flags differ between source files, artifact source paths must be
preserved; ambiguous flag selection is rejected. Smoke sources must have an
unambiguous compilation configuration.

Java is the third-backend architecture validation. Current real fixtures cover
top-level classes, static methods, primitive argument types and overloads. Full
build-system dependency resolution, generic type erasure and nested/local class
binary-name resolution are not established by these fixtures. Unresolved runtime
targets stay unverified. Python classes without an observable constructor body
also stay unverified. Compilation, import or successful assertions without an
observed entrypoint call never establish entrypoint coverage.

## Running the New Pipeline

Use the existing Python 3.12 installation instructions, then install the parsers:

```bash
.venv/bin/python -m pip install -e '.[multilanguage]'
```

The configuration template is
[`config/reference/multilanguage_pipeline.json`](../config/reference/multilanguage_pipeline.json).
Set its frozen source root, source commit, enabled languages, model and local
toolchain image. Language options are fields in each `languages` row, including
C++ `standard`, `target` and root-relative `compilation_database`.
The source snapshot must be available locally; dependencies must already be
installed in the image. The controller does not pull images or install packages.

```bash
.venv/bin/python tools/preflight.py --config /path/to/pipeline.json
.venv/bin/python -m component_method.workflow.multilanguage \
  --config /path/to/pipeline.json \
  --candidates /path/to/protocol_candidates_v2.json \
  --output /path/to/new-build-directory
```

Candidates come from the existing embedding/candidate preparation stages with
the same language configuration. The command checks canonical source references,
requires `OPENAI_API_KEY`, freezes source/backend/candidate/model identities,
resolves the local runtime image to its immutable ID, and runs the shared
extraction/review/repair/publication gates. `OPENAI_API_BASE` is optional when
using the default API endpoint. Existing output directories are preserved.
The preflight command requires no model call or historical 20-task dataset.
The pipeline command returns exit code `1` if any component's final validation
status is `failed`, including partial publication. The JSON summary and any
validated components remain available. No-component extraction and reviews
returning rejected or uncertain are normal outcomes and return exit code `0`.
Schema-8 task environments retain the repository root in `PYTHONPATH` before
Python component directories, including when task scripts run outside the repo.

An offline image assembly helper is provided for existing local base images:

```bash
.venv/bin/python tools/build_multilanguage_validation_image.py --help
```

It packages an existing JDK into a local base image without downloading or
running repository build scripts. The base distribution must satisfy that JDK's
system-library requirements.

## Verification

Baseline revision: `ee50cebca10f6a89fc211e690a797bc032b265e6`.
The original suite had 189 passed and 1 skipped. The frozen Python replay still
matches all eight stages: units, source records, clone/skeleton evidence,
semantic input, candidates, packets and normalized drafts.
Final verification with all Docker and DSH integration flags enabled:
**286 passed, 0 skipped**, in 69.59 seconds. `git diff --check` also passes.

```bash
.venv/bin/python tools/replay_python_baseline.py
.venv/bin/python tools/compare_python_backend.py
.venv/bin/python -m pytest
```

The production comparison reads source files from Git without checking out or
modifying the worktree. Results: 92 files, 536 units, 536 clone streams and 536
skeleton streams match the original implementation, including order, text,
coordinates and parser errors. Frozen source SHA-256:
`0eb42095aebc868f75dc10ec7b17236c84058862657fec92022fb40c55f1bcda`.

Real offline integration uses these locally available immutable images:

- Validation: `sha256:8d5fd26a7e297af2306027e73618fa5b4f3e02c49a346fb61aedd5e70b20728b`.
- Original task handoff: `sha256:f0c61a06f267d75fe348b22b139c4549917a2cc7fa4c949cff693bcee63f3b18`.

```bash
export COMPONENT_MULTILANGUAGE_IMAGE=sha256:8d5fd26a7e297af2306027e73618fa5b4f3e02c49a346fb61aedd5e70b20728b
export COMPONENT_ORIGINAL_TASK_IMAGE=sha256:f0c61a06f267d75fe348b22b139c4549917a2cc7fa4c949cff693bcee63f3b18
export COMPONENT_DSH_REAL_INTEGRATION=1
export COMPONENT_DSH_DOCKER_TEST_IMAGE="$COMPONENT_ORIGINAL_TASK_IMAGE"
.venv/bin/python -m pytest -o addopts='-ra'
```

Coverage includes a real mixed Python/C++/Java corpus, backend-order stability,
language-partitioned candidates, the same extraction/review orchestration for
all three backends, multi-file submissions, runtime calls versus no-call cases,
compilation database defines, exact overload observations, bounded repairs,
publication tampering, language-preserving retrieval and independent original
image loading/compilation for Python and C++. The DSH test uses a local model
fixture to exercise real tool calls and session recovery.

## Acceptance Still Requiring External Inputs

M1/M2 implementation and M3/M5 backend integration have local regression and
container evidence. M4's production acceptance is **not established**: this
session has no model credentials and no designated C++/Java formal benchmark
task. Fixture-based orchestration and Docker execution are not an actual Agent
extraction plus official task evaluation. The same limitation applies to claims
of full C++ phase-7 acceptance and third-language formal task acceptance.

The code paths, CLI, configuration and local verification are available. A
complete experimental acceptance still requires selecting a frozen target
repository, enabling the configured model service, performing real extraction
and review, and running its official evaluation in the original task image.
