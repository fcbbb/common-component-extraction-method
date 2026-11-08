"""Canonical unit identities for graphs, with reversible historical aliases."""

from copy import deepcopy


class GraphBackend:
    canonical_units = True

    def __init__(self, backend, units):
        self.backend = backend
        self.units = {unit.unit_key: unit for unit in units}
        self.aliases = {}
        self.ambiguous_aliases = set()
        for unit in units:
            alias = (unit.file_id, unit.metadata.get("legacy_unit_id", unit.unit_key))
            if alias in self.aliases:
                self.ambiguous_aliases.add(alias)
            self.aliases[alias] = unit.unit_key

    def file_token_streams(self, file_id, source, signal):
        from dataclasses import replace

        method = self.backend.normalized_tokens if signal == "clone" else self.backend.structural_tokens
        return [replace(method(unit), unit_id=unit.unit_key) for unit in self.backend.extract_units(file_id, source)], None

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def describe_unit_id(self, key):
        unit = self.units[key]
        return {"kind": unit.kind, "qualified_name": unit.qualified_name,
                "display_name": unit.display_name, "parent_qualified_name": unit.parent_qualified_name}

    def is_ancestor(self, parent, child):
        return self.backend.is_ancestor(self.units[parent["unit_id"]], self.units[child["unit_id"]])

    def signal(self, value):
        result = deepcopy(value)

        def walk(item):
            if isinstance(item, list):
                for child in item:
                    walk(child)
            elif isinstance(item, dict):
                for fk, uk in (("file_id", "unit_id"), ("file_a", "unit_a"),
                               ("file_b", "unit_b"), ("from_file_id", "from_unit_id")):
                    if fk in item and uk in item:
                        alias = (item[fk], item[uk])
                        if alias in self.aliases:
                            if alias in self.ambiguous_aliases:
                                raise ValueError("ambiguous alias in historical signal")
                            item[uk] = self.aliases[alias]
                for child in item.values():
                    walk(child)

        walk(result)
        return result

    def candidates(self, value):
        result = deepcopy(value)
        for candidate in result.get("candidates", []):
            candidate.update(language=self.language_id, backend_id=self.backend_id)
            for name in ("units", "seed_units", "expanded_units", "members"):
                for ref in candidate.get(name, []):
                    if not isinstance(ref, dict):
                        continue
                    key = ref.get("unit_id")
                    if key in self.units:
                        unit = self.units[key]
                        ref.update(unit_key=key, language=unit.language, backend_id=unit.backend_id)
                        ref["legacy_unit_id"] = unit.metadata.get("legacy_unit_id", key)
        return result
