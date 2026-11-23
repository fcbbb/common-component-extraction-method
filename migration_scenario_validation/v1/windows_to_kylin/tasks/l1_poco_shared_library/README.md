# l1_poco_shared_library — POCO SharedLibrary: LoadLibrary -> dlopen

- **Scenario**: `windows_to_kylin`
- **Level**: `L1`
- **Source**: https://github.com/pocoproject/poco.git @ `d6bd48a94c5f03e3c69cac1b024fdad5120e3a7b`
- **License**: BSL-1.0
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

Recreate `Foundation/src/SharedLibrary_UNIX.cpp`: load/UNLOAD shared objects, map Poco's Poco::SharedLibrary
exceptions onto the target loader error API, expose prefix/suffix helpers, and keep the
symbol lookup semantics (missing symbol must throw
Poco::SharedLibrary::SymbolNotFoundException, not return null).

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
