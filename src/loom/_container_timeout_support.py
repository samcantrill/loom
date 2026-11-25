"""Runtime identities qualified for foreground container timeout cleanup."""

DIRECT_BUILDS = ("3.10.4", "3.10.4-focal", "4.1.1", "4.1.5")
GUARD_VERSION = "loom-apptainer-guard version 1"
GUARD_RUNTIME = "apptainer version 1.5.3"
GUARD_UNSHARE = "unshare from util-linux 2.37.4"

QUALIFIED_COMMANDS = (
    f"SingularityCE {', '.join(DIRECT_BUILDS)} foreground exec or "
    f"{GUARD_VERSION} ({GUARD_RUNTIME}, {GUARD_UNSHARE})"
)


def supports_timeout(version_output: str) -> bool:
    if version_output.strip() == GUARD_VERSION:
        return True
    # Direct version output historically accepts trailing whitespace only.
    command, separator, build = version_output.rstrip().partition(" version ")
    return bool(separator) and command in {"singularity", "singularity-ce"} and build in DIRECT_BUILDS
