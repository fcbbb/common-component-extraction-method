#!/usr/bin/env python3
"""Add an installed JDK to a local task image without fetching dependencies."""

import argparse
import io
import json
from pathlib import Path
import tarfile
import tempfile

import docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", required=True)
    parser.add_argument("--jdk", type=Path, required=True)
    parser.add_argument("--tag", default="component-method/multilanguage-validation:local")
    args = parser.parse_args()
    if not (args.jdk / "bin/javac").is_file():
        raise ValueError("JDK directory must contain bin/javac")
    client = docker.from_env()
    base = client.images.get(args.base_image)
    dockerfile = f"FROM {base.id}\nCOPY jdk/ /opt/component-jdk/\n"
    config = Path("/etc") / args.jdk.name.replace("-amd64", "")
    if config.is_dir():
        dockerfile += f"COPY jdk-config/ {config.as_posix()}/\n"
    dockerfile += 'ENV JAVA_HOME=/opt/component-jdk\nENV PATH="/opt/component-jdk/bin:${PATH}"\n'
    with tempfile.TemporaryFile() as context:
        with tarfile.open(fileobj=context, mode="w") as archive:
            source = dockerfile.encode()
            info = tarfile.TarInfo("Dockerfile")
            info.size = len(source)
            archive.addfile(info, io.BytesIO(source))
            archive.add(args.jdk.resolve(), arcname="jdk")
            if config.is_dir():
                archive.add(config, arcname="jdk-config")
        context.seek(0)
        image, _ = client.images.build(fileobj=context, custom_context=True, tag=args.tag,
                                       network_mode="none", pull=False, rm=True)
    print(json.dumps({"image_id": image.id, "base_image_id": base.id, "tag": args.tag}, indent=2))


if __name__ == "__main__":
    main()
