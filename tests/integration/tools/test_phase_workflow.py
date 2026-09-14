"""Exercise delivery boundaries without contacting GitHub or touching real phases."""

from __future__ import annotations

from pathlib import Path
import json
import subprocess

import pytest

from tools import phase_workflow as workflow

pytestmark = pytest.mark.integration
PHASE = "stage-1-p1-small-change"
BRANCH = f"agent/{PHASE}"
TITLE = "Stage 1 Example - Phase 1: Small change"
HEAD = "a" * 40
MERGE = "b" * 40
ORIGIN_URLS = workflow._origin_urls


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    root = tmp_path / "control"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "clone", str(remote), str(root)], check=True, capture_output=True
    )
    git(root, "config", "user.name", "Workflow test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "checkout", "-b", "develop")
    (root / "source.txt").write_text("initial\n")
    git(root, "add", "source.txt")
    git(root, "commit", "-m", "Initial")
    git(root, "push", "origin", "develop")
    monkeypatch.setattr(
        workflow,
        "_origin_urls",
        lambda root: ["https://github.com/samcantrill/loom.git"],
    )
    return root, git(root, "rev-parse", "HEAD")


def test_setup_creates_stage_and_named_coordination_branch(repository, monkeypatch):
    root, base = repository
    result = workflow.setup(
        root, PHASE, base, [base], stage=1, worktree_root=root.parent / "worktrees"
    )
    worktree = Path(result["worktree"])
    assert worktree.name == "stage-1"
    assert result["branch"] == BRANCH
    assert result["coordination_branch"] == "agent/stage-1"
    assert git(worktree, "rev-parse", "HEAD", "agent/stage-1").splitlines() == [
        base,
        base,
    ]
    monkeypatch.chdir(worktree)
    assert (
        workflow.preflight(root, 1, BRANCH, worktree_root=root.parent / "worktrees")[
            "head"
        ]
        == base
    )
    with pytest.raises(ValueError, match="already exists"):
        workflow.setup(
            root, PHASE, base, [base], stage=1, worktree_root=root.parent / "worktrees"
        )


def test_setup_rejects_dirty_control_without_discarding_work(repository):
    root, base = repository
    (root / "source.txt").write_text("user changes")
    with pytest.raises(ValueError, match="dirty"):
        workflow.setup(
            root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )
    assert (root / "source.txt").read_text() == "user changes"
    assert not (root.parent / "worktrees").exists()


def test_setup_rejects_stale_approved_base(repository):
    root, base = repository
    git(root, "commit", "--allow-empty", "-m", "New develop")
    git(root, "push", "origin", "develop")
    with pytest.raises(ValueError, match="fetched origin/develop"):
        workflow.setup(
            root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )
    assert not (root.parent / "worktrees").exists()


def test_setup_rejects_unmerged_dependency(repository):
    root, base = repository
    git(root, "checkout", "-b", "unmerged")
    git(root, "commit", "--allow-empty", "-m", "Dependency")
    dependency = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "develop")
    with pytest.raises(RuntimeError):
        workflow.setup(
            root,
            PHASE,
            base,
            [dependency],
            stage=1,
            worktree_root=root.parent / "worktrees",
        )
    assert not (root.parent / "worktrees").exists()


def test_preflight_preserves_and_reports_dirty_phase_worktree(repository, monkeypatch):
    root, base = repository
    result = workflow.setup(
        root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
    )
    file = Path(result["worktree"]) / "source.txt"
    file.write_text("unfinished phase work")
    monkeypatch.chdir(file.parent)
    assert workflow.preflight(root, 1, BRANCH, worktree_root=root.parent / "worktrees")[
        "dirty"
    ]
    with pytest.raises(ValueError, match="stage worktree is dirty"):
        workflow.preflight(
            root, 1, BRANCH, clean=True, worktree_root=root.parent / "worktrees"
        )
    assert file.read_text() == "unfinished phase work"


def test_preflight_rejects_wrong_branch(repository, monkeypatch):
    root, base = repository
    result = workflow.setup(
        root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
    )
    worktree = Path(result["worktree"])
    git(worktree, "checkout", "-b", "unrelated")
    monkeypatch.chdir(worktree)
    with pytest.raises(ValueError, match="wrong branch"):
        workflow.preflight(root, 1, BRANCH, worktree_root=root.parent / "worktrees")
    assert git(worktree, "branch", "--show-current") == "unrelated"


def test_setup_does_not_repurpose_an_existing_branch(repository):
    root, base = repository
    git(root, "branch", BRANCH)
    with pytest.raises(ValueError, match="already exists"):
        workflow.setup(
            root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )
    assert git(root, "rev-parse", BRANCH) == base
    assert not (root.parent / "worktrees").exists()


@pytest.mark.parametrize(
    "phase", ["../escape", "stage-1-p0-change", "stage-1-p1-../change"]
)
def test_setup_rejects_noncanonical_phase_paths(repository, phase):
    root, base = repository
    with pytest.raises(ValueError, match="phase must"):
        workflow.setup(
            root, phase, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )
    assert not (root.parent / "worktrees").exists()


def pr(**changes):
    return {
        "number": 12,
        "title": TITLE,
        "baseRefName": "develop",
        "headRefName": BRANCH,
        "headRefOid": HEAD,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "url": "https://github.com/samcantrill/loom/pull/12",
        **changes,
    }


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    evidence = tmp_path / "phase.md"
    evidence.write_text(
        "Local gate passed; independent reviewer approved the recorded head.\n"
    )
    calls = []
    responses = [
        pr(),
        pr(state="MERGED", mergedAt="2026-09-07T00:00:00Z", mergeCommit={"oid": MERGE}),
    ]
    monkeypatch.setattr(workflow, "_pr", lambda number: responses.pop(0))

    def run(*args, **kwargs):
        calls.append(args)
        if args[:2] == ("gh", "api"):
            return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(workflow, "_run", run)
    monkeypatch.setattr(workflow, "preflight", lambda *a, **kw: {"head": HEAD})
    arguments = dict(
        stage=1,
        root=tmp_path,
        worktree_root=tmp_path / "worktrees",
        number=12,
        branch=BRANCH,
        title=TITLE,
        reviewed_head=HEAD,
        validated_head=HEAD,
        evidence_file=evidence,
        review_approved=True,
        local_validation_passed=True,
    )
    return arguments, responses, calls


def test_delivery_matches_reviewed_head_and_returns_verified_merge(delivery):
    arguments, responses, calls = delivery
    result = workflow.deliver(**arguments)
    merge = calls[0]
    assert merge == (
        "gh",
        "pr",
        "merge",
        "12",
        "--repo",
        "samcantrill/loom",
        "--squash",
        "--match-head-commit",
        HEAD,
    )
    assert result["merge_commit"] == MERGE and result["state"] == "MERGED"
    assert result["remote_branch"] == "deleted"
    assert not responses


@pytest.mark.parametrize(
    "change",
    [
        {"headRefOid": "c" * 40},
        {"headRefName": "other"},
        {"baseRefName": "main"},
        {"title": "Wrong phase"},
        {"number": 13},
        {"isDraft": True},
        {"mergeable": "CONFLICTING"},
        {"mergeable": "UNKNOWN"},
        {"state": "CLOSED"},
    ],
)
def test_delivery_rejects_wrong_or_unmergeable_pr_before_mutation(delivery, change):
    arguments, responses, calls = delivery
    responses[0] = pr(**change)
    with pytest.raises(ValueError):
        workflow.deliver(**arguments)
    assert calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"validated_head": "c" * 40},
        {"review_approved": False},
        {"local_validation_passed": False},
    ],
)
def test_delivery_requires_current_local_and_review_disposition(delivery, change):
    arguments, responses, calls = delivery
    with pytest.raises(ValueError):
        workflow.deliver(**(arguments | change))
    assert calls == [] and len(responses) == 2


def test_delivery_rechecks_remote_merge_after_cli_failure(delivery, monkeypatch):
    arguments, _, calls = delivery
    original = workflow._run

    def run(*args, **kwargs):
        if args[:3] == ("gh", "pr", "merge"):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 1, "", "connection lost after submission"
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_run", run)
    result = workflow.deliver(**arguments)
    assert result["state"] == "MERGED" and result["merge_commit"] == MERGE
    assert "connection lost" in result["merge_command_error"]


def test_delivery_does_not_treat_command_success_as_merge(delivery):
    arguments, responses, calls = delivery
    responses[1] = pr()
    with pytest.raises(RuntimeError, match="remote merge is not verified"):
        workflow.deliver(**arguments)
    assert len(calls) == 1  # No cleanup of an unmerged branch.


def test_delivery_can_resume_after_already_verified_merge(delivery):
    arguments, responses, calls = delivery
    responses.pop(0)
    result = workflow.deliver(**arguments)
    assert result["state"] == "MERGED"
    assert all(call[:2] == ("gh", "api") for call in calls)


def test_delivery_preserves_remote_branch_that_moved_after_review(
    delivery, monkeypatch
):
    arguments, _, calls = delivery
    original = workflow._run

    def run(*args, **kwargs):
        if args[:2] == ("gh", "api"):
            calls.append(args)
            return subprocess.CompletedProcess(
                args, 0, '{"object":{"sha":"changed"}}', ""
            )
        return original(*args, **kwargs)

    monkeypatch.setattr(workflow, "_run", run)
    result = workflow.deliver(**arguments)
    assert result["state"] == "MERGED" and result["remote_branch"].startswith(
        "retained"
    )
    assert all("DELETE" not in call for call in calls)


def test_remote_cleanup_deletes_only_matching_ref_and_verifies(monkeypatch):
    calls = []
    results = [
        (0, '{"object":{"sha":"' + HEAD + '"}}', ""),
        (0, "", ""),
        (1, "", "gh: Not Found (HTTP 404)"),
    ]

    def run(*args, **kwargs):
        calls.append(args)
        code, out, err = results.pop(0)
        return subprocess.CompletedProcess(args, code, out, err)

    monkeypatch.setattr(workflow, "_run", run)
    assert workflow._remote_branch(BRANCH, HEAD) == "deleted"
    assert calls[0][-1] == f"repos/samcantrill/loom/git/ref/heads/{BRANCH}"
    assert calls[1] == (
        "git",
        "push",
        "https://github.com/samcantrill/loom.git",
        f"--force-with-lease=refs/heads/{BRANCH}:{HEAD}",
        f":refs/heads/{BRANCH}",
    )


def test_remote_cleanup_does_not_claim_auth_failure_is_deletion(monkeypatch):
    monkeypatch.setattr(
        workflow,
        "_run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a,
            1,
            "",
            "HTTP 403: forbidden",
        ),
    )
    assert workflow._remote_branch(BRANCH, HEAD) == "unknown"


def test_remote_cleanup_lease_preserves_a_concurrent_push(repository, monkeypatch):
    root, old_head = repository
    git(root, "push", "origin", f"{old_head}:refs/heads/{BRANCH}")
    git(root, "commit", "--allow-empty", "-m", "Concurrent contributor")
    new_head = git(root, "rev-parse", "HEAD")
    remote = git(root, "remote", "get-url", "origin")
    read_count = 0

    def run(*args, **kwargs):
        nonlocal read_count
        if args[:2] == ("gh", "api"):
            read_count += 1
            head = old_head if read_count == 1 else new_head
            return subprocess.CompletedProcess(
                args, 0, '{"object":{"sha":"' + head + '"}}', ""
            )
        # Simulate a real push between reading the ref and deleting it.
        git(root, "push", "origin", f"{new_head}:refs/heads/{BRANCH}")
        return subprocess.run(
            ["git", "-C", str(root), "push", remote, *args[3:]],
            text=True,
            capture_output=True,
            check=False,
        )

    monkeypatch.setattr(workflow, "_run", run)
    assert workflow._remote_branch(BRANCH, old_head).startswith("retained")
    assert (
        git(root, "ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0] == new_head
    )


@pytest.fixture
def stage_repository(repository, monkeypatch):
    root, base = repository
    worktree = Path(
        workflow.setup(
            root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )["worktree"]
    )
    monkeypatch.chdir(worktree)
    return root, worktree, base


def merge_phase(root, worktree, monkeypatch, branch=BRANCH, number=12):
    """Produce a real remote squash merge in a separate clone, as GitHub would."""
    server = root.parent / f"server-{number}"
    remote = git(root, "remote", "get-url", "origin")
    subprocess.run(
        ["git", "clone", "--branch", "develop", remote, str(server)],
        check=True,
        capture_output=True,
    )
    git(server, "config", "user.name", "Workflow test")
    git(server, "config", "user.email", "test@example.invalid")
    (worktree / f"phase-{number}.txt").write_text("phase implementation")
    git(worktree, "add", f"phase-{number}.txt")
    git(worktree, "commit", "-m", "Phase")
    head = git(worktree, "rev-parse", "HEAD")
    git(worktree, "push", "origin", branch)
    git(server, "fetch", "origin")
    git(server, "merge", "--squash", f"origin/{branch}")
    git(server, "commit", "-m", "Squash phase")
    git(server, "push", "origin", "develop")
    merged = git(server, "rev-parse", "HEAD")
    record = pr(
        number=number,
        headRefName=branch,
        headRefOid=head,
        state="MERGED",
        mergedAt="2026-09-08T00:00:00Z",
        mergeCommit={"oid": merged},
    )
    monkeypatch.setattr(workflow, "_pr", lambda number: record)
    return record, server


def test_two_phases_reuse_stage_after_published_metadata(stage_repository, monkeypatch):
    root, worktree, base = stage_repository
    for number, phase in [(12, PHASE), (13, "stage-1-p2-next-change")]:
        branch = f"agent/{phase}"
        before = git(root, "rev-parse", "HEAD")
        record, _ = merge_phase(root, worktree, monkeypatch, branch, number)
        assert git(root, "rev-parse", "HEAD") == before
        result = workflow.transition(
            root, 1, phase, number, worktree_root=root.parent / "worktrees"
        )
        assert result["synchronized"] and result["head"] == record["mergeCommit"]["oid"]
        assert git(worktree, "branch", "--show-current") == "agent/stage-1"
        (worktree / "metadata.md").write_text(f"Phase {number} merged")
        git(worktree, "add", "metadata.md")
        git(worktree, "commit", "-m", "docs: phase metadata")
        metadata = git(worktree, "rev-parse", "HEAD")
        with pytest.raises(RuntimeError):
            workflow.start(
                root,
                1,
                "stage-1-p2-next-change",
                number,
                branch,
                worktree_root=root.parent / "worktrees",
            )
        assert git(worktree, "rev-parse", "HEAD") == metadata
        git(worktree, "push", "origin", "HEAD:refs/heads/develop")
        result = workflow.synchronize(root, 1, worktree_root=root.parent / "worktrees")
        assert (
            git(worktree, "rev-parse", "HEAD", "develop", "origin/develop").splitlines()
            == [metadata] * 3
        )
        assert not git(root, "status", "--porcelain")
        assert (
            workflow.synchronize(root, 1, worktree_root=root.parent / "worktrees")[
                "head"
            ]
            == metadata
        )  # Interrupted sync is resumable.
        if number == 12:
            result = workflow.start(
                root,
                1,
                "stage-1-p2-next-change",
                number,
                branch,
                worktree_root=root.parent / "worktrees",
            )
            assert result["base"] == metadata and Path(result["worktree"]) == worktree
    assert (worktree / "phase-12.txt").exists() and (worktree / "phase-13.txt").exists()


def test_preflight_rejects_control_or_another_stage(stage_repository, monkeypatch):
    root, worktree, _ = stage_repository
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="canonical stage"):
        workflow.preflight(root, 1, BRANCH, worktree_root=root.parent / "worktrees")
    monkeypatch.chdir(worktree)
    with pytest.raises(ValueError, match="canonical stage"):
        workflow.preflight(root, 2, BRANCH, worktree_root=root.parent / "worktrees")


@pytest.mark.parametrize(
    "changes",
    [{"state": "OPEN"}, {"baseRefName": "main"}, {"headRefName": "agent/unrelated"}],
)
def test_transition_waits_for_the_correct_remote_merge(
    stage_repository, monkeypatch, changes
):
    root, worktree, base = stage_repository
    monkeypatch.setattr(workflow, "_pr", lambda number: pr(**changes))
    with pytest.raises(ValueError, match="remote merge is not verified"):
        workflow.transition(root, 1, PHASE, 12, worktree_root=root.parent / "worktrees")
    assert git(worktree, "branch", "--show-current") == BRANCH
    assert git(root, "rev-parse", "HEAD") == base


def test_transition_preserves_commits_added_after_merge(stage_repository, monkeypatch):
    root, worktree, _ = stage_repository
    merge_phase(root, worktree, monkeypatch)
    git(worktree, "commit", "--allow-empty", "-m", "Unpublished follow-up")
    head = git(worktree, "rev-parse", "HEAD")
    with pytest.raises(ValueError, match="preserve extra local work"):
        workflow.transition(root, 1, PHASE, 12, worktree_root=root.parent / "worktrees")
    assert git(worktree, "rev-parse", "HEAD") == head
    assert git(worktree, "branch", "--show-current") == BRANCH


@pytest.mark.parametrize("state", ["dirty", "divergent"])
def test_transition_preserves_control_changes(stage_repository, monkeypatch, state):
    root, worktree, _ = stage_repository
    merge_phase(root, worktree, monkeypatch)
    if state == "dirty":
        (root / "source.txt").write_text("unrelated edits")
    else:
        git(root, "commit", "--allow-empty", "-m", "Local-only develop")
    before = git(root, "rev-parse", "HEAD")
    with pytest.raises((ValueError, RuntimeError)):
        workflow.transition(root, 1, PHASE, 12, worktree_root=root.parent / "worktrees")
    assert git(root, "rev-parse", "HEAD") == before
    assert git(worktree, "branch", "--show-current") == BRANCH
    if state == "dirty":
        assert (root / "source.txt").read_text() == "unrelated edits"


def test_sync_detects_remote_advancement_before_start(stage_repository, monkeypatch):
    root, worktree, _ = stage_repository
    _, server = merge_phase(root, worktree, monkeypatch)
    workflow.transition(root, 1, PHASE, 12, worktree_root=root.parent / "worktrees")
    original = workflow._git

    def concurrent(root, *args):
        if args[:1] == ("ls-remote",):
            git(server, "commit", "--allow-empty", "-m", "Remote advanced")
            git(server, "push", "origin", "develop")
        return original(root, *args)

    monkeypatch.setattr(workflow, "_git", concurrent)
    with pytest.raises(ValueError, match="remote develop advanced"):
        workflow.start(
            root,
            1,
            "stage-1-p2-next-change",
            12,
            BRANCH,
            worktree_root=root.parent / "worktrees",
        )
    assert git(worktree, "branch", "--show-current") == "agent/stage-1"


def test_delivery_rejects_different_local_head(delivery, monkeypatch):
    arguments, _, calls = delivery
    monkeypatch.setattr(workflow, "preflight", lambda *a, **kw: {"head": "c" * 40})
    with pytest.raises(ValueError, match="stage HEAD differs"):
        workflow.deliver(**arguments)
    assert calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/samcantrill/loom.git",
        "https://github.com/samcantrill/loom",
        "git@github.com:samcantrill/loom.git",
        "ssh://git@github.com/samcantrill/loom.git",
    ],
)
def test_repository_accepts_supported_loom_origins(tmp_path, monkeypatch, url):
    monkeypatch.setattr(workflow, "_origin_urls", lambda root: [url])
    workflow._repository(tmp_path)


@pytest.mark.parametrize(
    "urls",
    [
        ["https://github.com/samcantrill/rphys.git"],
        ["https://github.com/samcantrill/loom.git", "git@github.com:someone/fork.git"],
        ["https://another-host.invalid/samcantrill/loom.git"],
    ],
)
def test_setup_refuses_wrong_fetch_or_push_repository(repository, monkeypatch, urls):
    root, base = repository
    monkeypatch.setattr(workflow, "_origin_urls", lambda root: urls)
    with pytest.raises(ValueError, match="origin fetch and push"):
        workflow.setup(
            root, PHASE, base, [], stage=1, worktree_root=root.parent / "worktrees"
        )
    assert git(root, "rev-parse", "HEAD") == base
    assert not (root.parent / "worktrees").exists()


def test_repository_checks_effective_fetch_and_push_urls(repository, monkeypatch):
    root, _ = repository
    git(root, "remote", "set-url", "origin", "https://github.com/samcantrill/loom.git")
    git(
        root, "remote", "set-url", "--push", "origin", "git@github.com:someone/fork.git"
    )
    monkeypatch.setattr(workflow, "_origin_urls", ORIGIN_URLS)
    with pytest.raises(ValueError, match="origin fetch and push"):
        workflow._repository(root)
    assert ORIGIN_URLS(root) == [
        "https://github.com/samcantrill/loom.git",
        "git@github.com:someone/fork.git",
    ]


def test_stage_branch_must_belong_to_supplied_stage(stage_repository, monkeypatch):
    root, worktree, _ = stage_repository
    foreign = "agent/stage-2-p1-small-change"
    git(worktree, "switch", "-c", foreign)
    with pytest.raises(ValueError, match="supplied stage"):
        workflow.preflight(root, 1, foreign, worktree_root=root.parent / "worktrees")
    assert git(worktree, "branch", "--show-current") == foreign


def test_preflight_refuses_another_git_repository(repository, monkeypatch):
    root, _ = repository
    worktree_root = root.parent / "foreign"
    foreign = worktree_root / "stage-1"
    worktree_root.mkdir()
    subprocess.run(
        ["git", "clone", str(root), str(foreign)], check=True, capture_output=True
    )
    git(foreign, "switch", "-c", BRANCH)
    monkeypatch.chdir(foreign)
    with pytest.raises(ValueError, match="another repository"):
        workflow.preflight(root, 1, BRANCH, worktree_root=worktree_root)


def test_setup_from_linked_control_preserves_original_dirty_checkout(
    repository, monkeypatch
):
    original, base = repository
    git(original, "switch", "-c", "preserved")
    (original / "source.txt").write_text("unrelated local work")
    control = original.parent / "linked-control"
    git(original, "worktree", "add", str(control), "develop")
    worktree_root = original.parent / "worktrees"
    result = workflow.setup(
        control, PHASE, base, [], stage=1, worktree_root=worktree_root
    )
    monkeypatch.chdir(result["worktree"])
    assert (
        workflow.preflight(control, 1, BRANCH, worktree_root=worktree_root)["head"]
        == base
    )
    assert (original / "source.txt").read_text() == "unrelated local work"
    assert git(original, "branch", "--show-current") == "preserved"


def test_partial_setup_is_preserved_and_can_be_inspected(repository, monkeypatch):
    root, base = repository
    checks = 0
    original = workflow._advertised

    def advanced(root, base):
        nonlocal checks
        checks += 1
        if checks == 2:
            raise ValueError("remote develop advanced")
        original(root, base)

    monkeypatch.setattr(workflow, "_advertised", advanced)
    worktree_root = root.parent / "worktrees"
    with pytest.raises(ValueError, match="remote develop advanced"):
        workflow.setup(root, PHASE, base, [], stage=1, worktree_root=worktree_root)
    monkeypatch.chdir(worktree_root / "stage-1")
    assert (
        workflow.preflight(root, 1, BRANCH, worktree_root=worktree_root)["head"] == base
    )
    assert git(root, "rev-parse", "agent/stage-1") == base
    with pytest.raises(ValueError, match="already exists"):
        workflow.setup(root, PHASE, base, [], stage=1, worktree_root=worktree_root)


def test_cli_preflight_uses_explicit_paths(stage_repository, capsys):
    root, worktree, base = stage_repository
    assert (
        workflow.main(
            [
                "preflight",
                "--root",
                str(root),
                "--worktree-root",
                str(worktree.parent),
                "--stage",
                "1",
                "--branch",
                BRANCH,
            ]
        )
        == 0
    )
    facts = json.loads(capsys.readouterr().out)
    assert facts["worktree"] == str(worktree) and facts["head"] == base
