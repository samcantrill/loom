"""Bounded Git/GitHub mechanics for approved Loom phases (Python 3.12).

Run with ``uv run --locked --no-sync python tools/phase_workflow.py --help``.
Setup consumes an approved base and dependency revisions. Stage preflight and
transition commands own checkout identity and synchronization checks. Delivery consumes the
manager's explicit local-validation and independent-review dispositions, checks
the live PR head, and returns verified merge/remote cleanup facts as JSON. It
does not parse scientific acceptance from prose, dispatch CI, update lifecycle
artifacts, or delete local worktrees. The phase-loop prompt owns those decisions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY = "samcantrill/loom"
PHASE_SUFFIX = re.compile(r"stage-([1-9][0-9]*)-p[1-9][0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*")
SHA = re.compile(r"[0-9a-f]{40}")
PR_FIELDS = (
    "number,title,state,isDraft,baseRefName,headRefName,headRefOid,mergeable,"
    "mergedAt,mergeCommit,url"
)


def _run(
    *args: str, cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if check and result.returncode:
        raise RuntimeError(
            result.stderr.strip() or result.stdout.strip() or f"{args[0]} failed"
        )
    return result


def _git(root: Path, *args: str) -> str:
    return _run("git", "-C", str(root), *args).stdout.strip()


def _require_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        raise ValueError("use a full 40-character commit SHA")
    return value


def _require_ancestor(root: Path, ancestor: str, descendant: str) -> None:
    _require_sha(ancestor)
    _require_sha(descendant)
    _git(root, "merge-base", "--is-ancestor", ancestor, descendant)


def _stage_path(stage: int, worktree_root: Path) -> Path:
    if stage < 1:
        raise ValueError("stage must be positive")
    return worktree_root.resolve() / f"stage-{stage}"


def _phase_branch(phase: str, stage: int) -> str:
    match = PHASE_SUFFIX.fullmatch(phase)
    if not match or int(match[1]) != stage:
        raise ValueError(
            "phase must be stage-<N>-p<P>-<phase-slug> for the supplied stage"
        )
    return f"agent/{phase}"


def _origin_urls(root: Path) -> list[str]:
    return [
        *_git(root, "remote", "get-url", "--all", "origin").splitlines(),
        *_git(root, "remote", "get-url", "--push", "--all", "origin").splitlines(),
    ]


def _repository(root: Path) -> None:
    urls = _origin_urls(root)
    pattern = rf"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/){REPOSITORY}(?:\.git)?/?"
    if not urls or any(not re.fullmatch(pattern, url) for url in urls):
        raise ValueError(
            "origin fetch and push URLs must identify samcantrill/loom on GitHub"
        )


def _control(root: Path) -> None:
    _repository(root)
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root.resolve():
        raise ValueError("root must be the control checkout root")
    if _git(root, "branch", "--show-current") != "develop":
        raise ValueError("control checkout must be on develop")
    if _git(root, "status", "--porcelain"):
        raise ValueError("control checkout is dirty; preserve it")


def _fetch(root: Path) -> str:
    _git(root, "fetch", "origin", "refs/heads/develop:refs/remotes/origin/develop")
    return _git(root, "rev-parse", "origin/develop")


def _advertised(root: Path, base: str) -> None:
    remote = _git(root, "ls-remote", "--exit-code", "origin", "refs/heads/develop")
    if remote.split()[0] != base:
        raise ValueError(
            "remote develop advanced; repeat synchronization before continuing"
        )


def preflight(
    root: Path, stage: int, branch: str, *, worktree_root: Path, clean: bool = False
) -> dict:
    """Check the actual cwd, shared repository, and assigned branch without mutation.

    In-phase edits are allowed and reported. Transitions require ``clean=True``.
    This is an admission check, not a sandbox against subsequent arbitrary writes.
    """
    worktree = _stage_path(stage, worktree_root).resolve()
    actual = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel")).resolve()
    if actual != worktree or worktree == root.resolve():
        raise ValueError(
            "run from the canonical stage worktree, not the control checkout"
        )
    _repository(root)
    common = ("rev-parse", "--path-format=absolute", "--git-common-dir")
    if _git(worktree, *common) != _git(root, *common):
        raise ValueError("stage worktree belongs to another repository")
    if branch != f"agent/stage-{stage}":
        if not branch.startswith("agent/"):
            raise ValueError("expected this stage's phase or coordination branch")
        _phase_branch(branch[6:], stage)
    if _git(worktree, "branch", "--show-current") != branch:
        raise ValueError("stage worktree has the wrong branch; preserve it")
    dirty = bool(_git(worktree, "status", "--porcelain"))
    if clean and dirty:
        raise ValueError("stage worktree is dirty; preserve it before transition")
    return {
        "branch": branch,
        "worktree": str(worktree),
        "head": _git(worktree, "rev-parse", "HEAD"),
        "dirty": dirty,
    }


def setup(
    root: Path,
    phase: str,
    base: str,
    dependencies: list[str],
    *,
    stage: int,
    worktree_root: Path,
) -> dict:
    """Bootstrap one stage and its first pending phase without touching control files.

    Startup receipts/corrections join that phase's PR. The named coordination
    branch starts at the same base and later owns post-merge metadata/closeout.
    Resume uses preflight; an occupied stage path or branch is never repurposed.
    """
    branch = _phase_branch(phase, stage)
    worktree = _stage_path(stage, worktree_root)
    coordination = f"agent/stage-{stage}"
    _require_sha(base)
    _control(root)
    if _fetch(root) != base:
        raise ValueError("approved base does not match fetched origin/develop")
    for dependency in dependencies:
        _require_ancestor(root, dependency, base)
    _require_ancestor(root, _git(root, "rev-parse", "HEAD"), base)
    records = _git(root, "worktree", "list", "--porcelain")
    if worktree.exists() or f"worktree {worktree}\n" in records:
        raise ValueError("stage path already exists; resume with preflight")
    for name in (branch, coordination):
        exists = _run(
            "git",
            "-C",
            str(root),
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/heads/{name}",
            check=False,
        )
        if exists.returncode != 1:
            raise ValueError("stage or phase branch already exists; preserve it")
    _advertised(root, base)
    _git(root, "merge", "--ff-only", base)
    worktree_root.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-b", branch, str(worktree), base)
    _git(worktree, "branch", coordination, base)
    _advertised(worktree, base)
    return {
        "branch": branch,
        "coordination_branch": coordination,
        "worktree": str(worktree),
        "base": base,
    }


def _merged(number: int, branch: str, stage: int) -> dict:
    _phase_branch(branch.removeprefix("agent/"), stage)
    if not branch.startswith("agent/") or number < 1:
        raise ValueError("provide the previous phase PR and branch")
    pr = _pr(number)
    if any(
        pr.get(k) != v
        for k, v in {
            "number": number,
            "baseRefName": "develop",
            "headRefName": branch,
            "state": "MERGED",
        }.items()
    ) or not pr.get("mergedAt"):
        raise ValueError("previous phase remote merge is not verified")
    _require_sha(pr.get("mergeCommit", {}).get("oid", ""))
    return pr


def synchronize(root: Path, stage: int, *, worktree_root: Path) -> dict:
    """Fast-forward only published coordination work and local develop.

    Refuse unpublished/divergent commits, dirty checkouts, or remote advancement.
    No commits, pushes, resets, metadata edits, or phase branch deletion occur.
    """
    facts = preflight(
        root, stage, f"agent/stage-{stage}", clean=True, worktree_root=worktree_root
    )
    worktree = Path(facts["worktree"])
    _control(root)
    base = _fetch(worktree)
    _require_ancestor(worktree, facts["head"], base)
    _require_ancestor(root, _git(root, "rev-parse", "HEAD"), base)
    _git(worktree, "merge", "--ff-only", base)
    _git(root, "merge", "--ff-only", base)
    if (
        _git(worktree, "rev-parse", "HEAD", "develop", "origin/develop").splitlines()
        != [base] * 3
    ):
        raise ValueError("stage/local/remote revisions differ; stop before continuing")
    _advertised(worktree, base)
    preflight(root, stage, facts["branch"], clean=True, worktree_root=worktree_root)
    _control(root)
    return facts | {"head": base, "base": base, "synchronized": True}


def transition(
    root: Path, stage: int, phase: str, number: int, *, worktree_root: Path
) -> dict:
    """Verify the phase's remote merge and enter its named coordination branch.

    The phase HEAD must still match the merged PR head. Additional local commits
    are preserved and need manager reconciliation before retrying. Repeating on
    the coordination branch is safe only after its local work is published.
    """
    branch = _phase_branch(phase, stage)
    coordination = f"agent/stage-{stage}"
    worktree = _stage_path(stage, worktree_root)
    current = _git(Path.cwd(), "branch", "--show-current")
    facts = preflight(
        root,
        stage,
        coordination if current == coordination else branch,
        clean=True,
        worktree_root=worktree_root,
    )
    _control(root)
    pr = _merged(number, branch, stage)
    if current == branch and facts["head"] != pr.get("headRefOid"):
        raise ValueError(
            "phase HEAD differs from merged PR head; preserve extra local work"
        )
    base = _fetch(worktree)
    _require_ancestor(worktree, pr["mergeCommit"]["oid"], base)
    _require_ancestor(worktree, _git(worktree, "rev-parse", coordination), base)
    _require_ancestor(root, _git(root, "rev-parse", "HEAD"), base)
    _git(worktree, "switch", coordination)
    return synchronize(root, stage, worktree_root=worktree_root) | {
        "pr": number,
        "merge_commit": pr["mergeCommit"]["oid"],
    }


def start(
    root: Path,
    stage: int,
    phase: str,
    number: int,
    previous_branch: str,
    *,
    worktree_root: Path,
) -> dict:
    """Start a fresh phase only after the prior merge and metadata publication.

    The manager owns phase ordering and required metadata contents. Equality of
    the coordination branch to fetched/advertised develop verifies publication.
    """
    branch = _phase_branch(phase, stage)
    preflight(
        root, stage, f"agent/stage-{stage}", clean=True, worktree_root=worktree_root
    )
    pr = _merged(number, previous_branch, stage)
    facts = synchronize(root, stage, worktree_root=worktree_root)
    worktree = Path(facts["worktree"])
    _require_ancestor(worktree, pr["mergeCommit"]["oid"], facts["base"])
    _git(worktree, "switch", "--no-track", "-c", branch, facts["base"])
    return preflight(root, stage, branch, clean=True, worktree_root=worktree_root) | {
        "base": facts["base"]
    }


def _pr(number: int) -> dict:
    return json.loads(
        _run(
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            REPOSITORY,
            "--json",
            PR_FIELDS,
        ).stdout
    )


def _identity(pr: dict, number: int, branch: str, title: str, head: str) -> None:
    expected = {
        "number": number,
        "baseRefName": "develop",
        "headRefName": branch,
        "title": title,
        "headRefOid": head,
    }
    for field, value in expected.items():
        if pr.get(field) != value:
            raise ValueError(f"PR {field} differs from the approved delivery input")


def _remote_branch(branch: str, head: str) -> str:
    """Delete only the reviewed remote ref after merge; retain moved/unknown refs."""
    endpoint = f"repos/{REPOSITORY}/git/ref/heads/{branch}"
    result = _run("gh", "api", endpoint, check=False)
    if result.returncode:
        return "deleted" if "HTTP 404" in result.stderr else "unknown"
    if json.loads(result.stdout).get("object", {}).get("sha") != head:
        return "retained: branch moved after review"
    # A lease closes the read/delete race with a push to this branch after review.
    _run(
        "git",
        "push",
        f"https://github.com/{REPOSITORY}.git",
        f"--force-with-lease=refs/heads/{branch}:{head}",
        f":refs/heads/{branch}",
        check=False,
    )
    result = _run("gh", "api", endpoint, check=False)
    if result.returncode:
        return "deleted" if "HTTP 404" in result.stderr else "unknown"
    return "retained: cleanup required"


def deliver(
    number: int,
    branch: str,
    title: str,
    reviewed_head: str,
    validated_head: str,
    evidence_file: Path,
    *,
    stage: int,
    root: Path,
    worktree_root: Path,
    review_approved: bool,
    local_validation_passed: bool,
) -> dict:
    """Merge the exact reviewed head after explicit local gate disposition.

    The manager supplies an existing nonempty evidence file and attestations.
    ``validated_head`` is the head to which that evidence has been reconciled,
    including recorded validation-irrelevant changes after the actual test run.
    Relevant changes require fresh affected checks. This helper cannot validate
    scientific review or test coverage from prose. It never force-merges or
    treats an ambiguous CLI exit as evidence of merge.
    """
    if (
        number < 1
        or not branch.startswith("agent/")
        or not PHASE_SUFFIX.fullmatch(branch[6:])
    ):
        raise ValueError("provide a positive PR number and canonical phase branch")
    _phase_branch(branch[6:], stage)
    _require_sha(reviewed_head)
    _require_sha(validated_head)
    if reviewed_head != validated_head:
        raise ValueError("local evidence is not reconciled to the reviewed head")
    if not review_approved or not local_validation_passed:
        raise ValueError(
            "independent review and local validation must be explicitly accepted"
        )
    if not evidence_file.is_file() or not evidence_file.read_text().strip():
        raise ValueError(
            "provide the existing nonempty local review/validation evidence file"
        )
    facts = preflight(root, stage, branch, clean=True, worktree_root=worktree_root)
    if facts["head"] != reviewed_head:
        raise ValueError("stage HEAD differs from reviewed head")
    pr = _pr(number)
    _identity(pr, number, branch, title, reviewed_head)
    command_error = None
    if pr.get("state") != "MERGED":
        if (
            pr.get("state") != "OPEN"
            or pr.get("isDraft")
            or pr.get("mergeable") != "MERGEABLE"
        ):
            raise ValueError("PR must be open, non-draft, and mergeable")
        result = _run(
            "gh",
            "pr",
            "merge",
            str(number),
            "--repo",
            REPOSITORY,
            "--squash",
            "--match-head-commit",
            reviewed_head,
            check=False,
        )
        if result.returncode:
            command_error = (
                result.stderr.strip() or result.stdout.strip() or "merge command failed"
            )
        # Verify even on failure: the request may have succeeded remotely.
        pr = _pr(number)
        _identity(pr, number, branch, title, reviewed_head)
    if pr.get("state") != "MERGED" or not pr.get("mergedAt"):
        raise RuntimeError(
            command_error or "remote merge is not verified; inspect the PR"
        )
    merge_commit = pr.get("mergeCommit", {}).get("oid")
    if not isinstance(merge_commit, str) or not SHA.fullmatch(merge_commit):
        raise RuntimeError("merged PR lacks a verified merge commit")
    return {
        "pr": number,
        "url": pr.get("url"),
        "state": "MERGED",
        "reviewed_head": reviewed_head,
        "merge_commit": merge_commit,
        "merged_at": pr["mergedAt"],
        "remote_branch": _remote_branch(branch, reviewed_head),
        "merge_command_error": command_error,
        "local_cleanup": "retain stage worktree; synchronize and retire only the verified phase branch",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser(
        "setup", help="verify base/dependencies and set up one worktree"
    )
    setup_parser.add_argument("--root", type=Path, required=True)
    setup_parser.add_argument("--worktree-root", type=Path, required=True)
    setup_parser.add_argument("--stage", type=int, required=True)
    setup_parser.add_argument(
        "--phase", required=True, help="stage-<N>-p<P>-<phase-slug>"
    )
    setup_parser.add_argument(
        "--base", required=True, help="approved full origin/develop SHA"
    )
    setup_parser.add_argument(
        "--dependency", action="append", default=[], help="required merge SHA"
    )
    delivery = commands.add_parser(
        "deliver", help="merge an explicitly reviewed and validated PR head"
    )
    delivery.add_argument("--stage", type=int, required=True)
    delivery.add_argument("--root", type=Path, required=True)
    delivery.add_argument("--worktree-root", type=Path, required=True)
    delivery.add_argument("--pr", type=int, required=True)
    delivery.add_argument("--branch", required=True)
    delivery.add_argument("--title", required=True)
    delivery.add_argument("--reviewed-head", required=True)
    delivery.add_argument("--validated-head", required=True)
    delivery.add_argument("--evidence-file", type=Path, required=True)
    delivery.add_argument("--review-approved", action="store_true", required=True)
    delivery.add_argument(
        "--local-validation-passed", action="store_true", required=True
    )
    for name in ("preflight", "transition", "sync", "start"):
        command = commands.add_parser(name, help=f"stage {name} gate")
        command.add_argument("--stage", type=int, required=True)
        command.add_argument("--root", type=Path, required=True)
        command.add_argument("--worktree-root", type=Path, required=True)
        if name == "preflight":
            command.add_argument("--branch", required=True)
            command.add_argument("--clean", action="store_true")
        if name in ("transition", "start"):
            command.add_argument("--phase", required=True)
            command.add_argument(
                "--pr", type=int, required=True, help="previous/merged phase PR"
            )
        if name == "start":
            command.add_argument("--previous-branch", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            result = setup(
                args.root,
                args.phase,
                args.base,
                args.dependency,
                stage=args.stage,
                worktree_root=args.worktree_root,
            )
        elif args.command == "preflight":
            result = preflight(
                args.root,
                args.stage,
                args.branch,
                clean=args.clean,
                worktree_root=args.worktree_root,
            )
        elif args.command == "transition":
            result = transition(
                args.root,
                args.stage,
                args.phase,
                args.pr,
                worktree_root=args.worktree_root,
            )
        elif args.command == "sync":
            result = synchronize(
                args.root, args.stage, worktree_root=args.worktree_root
            )
        elif args.command == "start":
            result = start(
                args.root,
                args.stage,
                args.phase,
                args.pr,
                args.previous_branch,
                worktree_root=args.worktree_root,
            )
        else:
            result = deliver(
                args.pr,
                args.branch,
                args.title,
                args.reviewed_head,
                args.validated_head,
                args.evidence_file,
                stage=args.stage,
                root=args.root,
                review_approved=args.review_approved,
                local_validation_passed=args.local_validation_passed,
                worktree_root=args.worktree_root,
            )
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
