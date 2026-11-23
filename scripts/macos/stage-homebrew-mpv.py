"""Stage libmpv and its non-system Mach-O dependencies for a macOS test build."""

import shutil
import subprocess
import sys
from pathlib import Path


def run(*args):
    return subprocess.check_output(args, text=True)


def resolve_dependency(source, dependency):
    if dependency.startswith("@rpath/"):
        name = dependency.removeprefix("@rpath/")
        candidates = [source.resolve().parent / name]
        load_commands = run("otool", "-l", source).splitlines()
        for index, line in enumerate(load_commands):
            if line.strip() == "cmd LC_RPATH":
                path = load_commands[index + 2].strip().removeprefix("path ").split(" (offset ", 1)[0]
                path = path.replace("@loader_path", str(source.resolve().parent), 1)
                candidates.append(Path(path) / name)
        candidates.append(Path(run("brew", "--prefix").strip()) / "lib" / name)
    else:
        candidates = [Path(dependency.replace("@loader_path/", f"{source.resolve().parent}/", 1))]
    for path in candidates:
        if path.is_absolute() and path.is_file():
            return path
    raise ValueError(f"Cannot resolve {dependency} from {source}")


def stage_library(source, name, destination, staged):
    if name in staged:
        if staged[name] != source.resolve():
            raise ValueError(f"Two libraries would be staged as {name}")
        return
    staged[name] = source.resolve()

    target = destination / name
    shutil.copyfile(source, target)
    target.chmod(0o755)
    identity = run("otool", "-D", source).splitlines()[1].strip()
    changes = []
    for line in run("otool", "-L", source).splitlines()[1:]:
        dependency = line.strip().split(" (compatibility version", 1)[0]
        if dependency == identity or dependency.startswith(("/usr/lib/", "/System/Library/")):
            continue
        path = resolve_dependency(source, dependency)
        stage_library(path, path.name, destination, staged)
        changes.extend(("-change", dependency, f"@loader_path/{path.name}"))

    run("install_name_tool", "-id", f"@rpath/{name}", *changes, target)
    run("codesign", "--force", "--sign", "-", target)


if __name__ == "__main__":
    mpv_prefix = Path(run("brew", "--prefix", "mpv").strip())
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True)
    stage_library(mpv_prefix / "lib/libmpv.2.dylib", "libmpv.2.dylib", output, {})
