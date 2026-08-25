"""Thin GitHub client used for issue polling (Phase 2) and, from Phase 6,
branch/commit/PR creation.

Deliberate substitution, documented here and in the README: the assignment
names `langchain_community.agent_toolkits.github.GitHubToolkit` for this.
The installed version (langchain-community==0.4.2) backs that toolkit with
`GitHubAPIWrapper`, whose `validate_environment` supports *only* GitHub App
authentication (`Auth.AppAuth`, app id + private key + installing the app on
the repo) - there is no personal-access-token code path at all. Standing up
a GitHub App just to poll a single demo repo is disproportionate setup for
this project, so this wraps PyGithub directly - the same library
`GitHubAPIWrapper` itself uses underneath - with plain PAT auth instead. The
required *behavior* (list/filter issues, create branches, open PRs) is
identical either way; only the auth mechanism differs.
"""
from __future__ import annotations

from github import Auth, Github, GithubException
from github.InputGitTreeElement import InputGitTreeElement
from github.Issue import Issue as GHIssue
from github.PullRequest import PullRequest as GHPullRequest

from src.codepilot.config import settings
from src.codepilot.orchestrator.issue import Issue


class MergeConflict(RuntimeError):
    """The target branch moved out from under us in a way that isn't a
    fast-forward - the closest real-world equivalent of a merge conflict
    for the GitHub Contents/Git-Data API flow used here (there is no local
    working tree to run a traditional 3-way merge on)."""


def estimate_complexity(title: str, body: str) -> int:
    """Cheap v1 complexity proxy (1-10), based on issue body length.

    Component 1 requires filtering "unassigned issues below a configurable
    complexity threshold" without mandating how complexity is scored. The
    'Issue triage scoring' bonus challenge asks for an LLM-scored 1-10
    estimate using the Repo Map + issue description; this heuristic is the
    placeholder until that bonus is built, and is deliberately isolated in
    its own function so swapping it later is a one-line change.
    """
    word_count = len((body or "").split())
    return min(1 + word_count // 40, 10)


class GitHubClient:
    def __init__(self, *, token: str | None = None, repo_full_name: str | None = None) -> None:
        settings.validate_for_github()
        token = token or settings.github_token
        repo_full_name = repo_full_name or settings.github_repo
        self._gh = Github(auth=Auth.Token(token))
        self.repo = self._gh.get_repo(repo_full_name)

    def list_candidate_issues(self, *, complexity_threshold: int) -> list[Issue]:
        """Open issues labelled `ai-assignable`, OR unassigned issues at or
        below `complexity_threshold`. Pull requests (which GitHub's issues
        endpoint also returns) are excluded.
        """
        candidates: list[Issue] = []
        for gh_issue in self.repo.get_issues(state="open"):
            if gh_issue.pull_request is not None:
                continue
            if is_candidate(gh_issue, complexity_threshold):
                candidates.append(to_issue(gh_issue))
        return candidates

    def get_default_branch(self) -> str:
        return self.repo.default_branch

    def commit_files_to_branch(self, *, branch: str, files: dict[str, str], message: str) -> str:
        """Creates `branch` off the default branch's current HEAD (or
        fast-forwards it if the branch already exists) with ONE commit
        containing all of `files` (repo-relative path -> new content).
        Returns the new commit sha.

        Uses the Git Data API (tree/commit/ref) rather than the simpler
        Contents API (`create_file`/`update_file`) so multiple files land
        in a single structured commit instead of one commit per file.
        """
        default_branch = self.get_default_branch()
        base_ref = self.repo.get_git_ref(f"heads/{default_branch}")
        base_commit = self.repo.get_git_commit(base_ref.object.sha)

        elements = [
            InputGitTreeElement(path=path, mode="100644", type="blob", content=content)
            for path, content in files.items()
        ]
        new_tree = self.repo.create_git_tree(elements, base_tree=base_commit.tree)
        new_commit = self.repo.create_git_commit(message, new_tree, [base_commit])

        try:
            self.repo.create_git_ref(f"refs/heads/{branch}", new_commit.sha)
        except GithubException as exc:
            if exc.status == 422:  # ref already exists - fast-forward it
                existing_ref = self.repo.get_git_ref(f"heads/{branch}")
                try:
                    existing_ref.edit(new_commit.sha, force=False)
                except GithubException as ff_exc:
                    raise MergeConflict(
                        f"branch {branch!r} could not be fast-forwarded to the new commit "
                        f"(status {ff_exc.status}) - it has diverged."
                    ) from ff_exc
            else:
                raise

        return new_commit.sha

    def open_pull_request(
        self,
        *,
        branch: str,
        base: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        reviewer: str | None = None,
    ) -> GHPullRequest:
        pr = self.repo.create_pull(base=base, head=branch, title=title, body=body)
        if labels:
            pr.add_to_labels(*labels)
        if reviewer:
            try:
                pr.create_review_request(reviewers=[reviewer])
            except GithubException:
                # e.g. reviewer is the PR author, or lacks repo access -
                # non-fatal, the PR itself is still open.
                pass
        return pr


def is_candidate(gh_issue: GHIssue, complexity_threshold: int) -> bool:
    labels = {label.name for label in gh_issue.labels}
    if "ai-assignable" in labels:
        return True
    is_unassigned = gh_issue.assignee is None and not gh_issue.assignees
    if not is_unassigned:
        return False
    return estimate_complexity(gh_issue.title, gh_issue.body or "") <= complexity_threshold


def to_issue(gh_issue: GHIssue) -> Issue:
    return Issue(
        id=str(gh_issue.number),
        number=gh_issue.number,
        title=gh_issue.title,
        body=gh_issue.body or "",
        labels=[label.name for label in gh_issue.labels],
        reporter=gh_issue.user.login if gh_issue.user else None,
    )
