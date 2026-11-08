"""Historical Python task import layout, retained for existing bundles."""

DIRECT_PYTHONPATH = "/testbed"
COMPONENT_PYTHONPATH = "/testbed:/testbed/component_bundle"


def legacy_environment(repository_root="/testbed", components=False, bundle_root=None):
    paths = [repository_root]
    if components:
        paths.append(bundle_root or repository_root + "/component_bundle")
    return {"PYTHONPATH": ":".join(paths)}
