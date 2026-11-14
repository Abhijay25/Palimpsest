# Conversation and worktree orchestration

Status: PHASE 2 RUNNING — D1–D6 approved; T01 baseline committed at e6d6e657ffe2a10bc7a598bc85f2ab1223741b7f. Three visible Luna workers launched and verified.
Owner: the orchestrator conversation in which the user invoked the pasted SDD prompt.

## Verified current state and model gate

Current conversation reference: `01a1d73c-67b4-7e93-9c0b-481a1ac02503`, read from CODEX_THREAD_ID.
Target checkout: /Users/zhenghaofang/Coding Playground/junction-2026/Palimpsest.
Inspected branch/base: `infra-set-up` / `17b73fc0c285f38a036160679d469cc49ace9b5d`.
Requested orchestrator: GPT-6.1 Sol, High reasoning or stronger. Requested workers: GPT-6 Luna.
**Verified actual orchestrator: gpt-6.1-sol, high reasoning.** Evidence: latest turn_context in the current conversation’s session metadata, turn 01a1d768-0dc8-7fd3-8e9d-0c6d54a8c7b1, inspected 2026-11-14. Reconfirm if the session settings change; this is not a claim about future worker settings.

Available tool schemas expose separate Codex chat creation with model/thinking controls, status waits, messages and worktree environments. Discovery is not proof of successful model selection or ready worker worktrees. The user confirmed Palimpsest is the primary source folder in the existing HackJunction project (c9b42133-91da-485c-b63a-237f9b57be47). list_projects exposes only one representative path; it does not enumerate all source folders. Workers were created in that project, then created managed worktrees using explicit Palimpsest sourceRoot before any implementation. Each worktree/remote/base was independently verified. Actual worker session metadata confirms gpt-6-luna, high reasoning. Worker B’s coordination message was rejected by automatic approval review for missing trusted authorization; the orchestrator reads B’s conversation through wait_threads instead, without bypassing that rejection.

## Human authorization and boundaries

The user explicitly authorizes, after specification approval, up to three visible worker conversations and their isolated worktrees, task assignment, progress monitoring, coordination/repair messages, and worker replies to this orchestrator for this infrastructure assignment only. Include that human authorization verbatim from the originating prompt plus this conversation reference in every worker brief; follow tool access checks. This is not permission to message unrelated chats or third parties.

One agent equals one separate visible Codex conversation. This chat remains the sole orchestrator. No role-play agents, hidden internal subagents, worker-spawned agents or additional reviewer agent. At most three Luna workers plus this Sol orchestrator. Reuse each worker conversation for its coherent workstream and repairs. An idle/completed worker's preserved conversation is not a newly spawned worker.

## Actual worker registry

| Slot/title | Model request | Planned work | Planned branch | Chat ID / path / baseline / commits | Status |
|---|---|---|---|---|---|
| A — Palimpsest infra: runtime | gpt-6-luna, high (verified) | T02,T03 | infra/runtime | Chat 01a1d76f-1381-7c72-822a-e29d4d5a2e9a; local host; /Users/zhenghaofang/.codex/worktrees/palimpsest-a/Palimpsest; base e6d6e65; no delivered commits yet | RUNNING |
| B — Palimpsest infra: data | gpt-6-luna, high (verified) | T04–T07,T10 | infra/data | Chat 01a1d76f-2107-7253-9e88-bd25c5cfbf03; local host; /Users/zhenghaofang/.codex/worktrees/palimpsest-b/Palimpsest; base e6d6e65; no delivered commits yet | RUNNING |
| C — Palimpsest infra: verification | gpt-6-luna, high (verified) | T08 | infra/verification | Chat 01a1d76f-2c1e-7071-b5d4-d409f46a9f7e; local host; /Users/zhenghaofang/.codex/worktrees/palimpsest-c/Palimpsest; base e6d6e65; no delivered commits yet | RUNNING |
| Orchestrator — this chat | gpt-6.1-sol, high or stronger | T00,T01,T09,T11 | infra-set-up (verify before use) | Current chat above; approved baseline e6d6e65 | INTEGRATION PREPARATION |

Orchestrator alone updates this registry with actual chat/host IDs, confirmed model/reasoning, worktree paths, base SHA, owned tasks/files, dependencies, status, test-environment allocation, delivered commits and review findings. Missing identifiers stay unassigned, never invented.

## Launch and coordination protocol

1. Owner approves D1–D6. Record approval and resolved scope. Verify orchestrator model. Freeze C1–C5 contracts/task file ownership, then create an approved specification/integration baseline commit (no commits during Phase 1).
2. Prepare isolated task branches/worktrees from that recorded commit. Check existing branches/worktrees before creating; never overwrite prior work. Create visible worker conversations via app tools with explicit Luna selection and assigned environment. Confirm async setup finished and actual branch/base match before starting edits. Tool starting-state restrictions must be respected; create task branches through supported Git operations when needed, not by inventing tool return values.
3. Initially launch A and B; launch C concurrently only when test contracts are stable and its independent fixture work is useful. Maximum is three workers, not a quota.
4. Give each worker the brief below. Workers report contract problems before editing another owner's files. Orchestrator resolves shared decisions and sends updates to every affected chat; main-chat context is not automatically propagated.
5. Poll compact bounded thread status snapshots; keep per-chat cursors and avoid repeated full transcript reads. A created chat is not a completed task. Use explicit messages for decisions, blockers, delivery and repair. Workers may reply only within the human-authorized coordination scope.
6. Require a handoff with committed SHA(s), actual changed files, executed commands/results, limitations and requested shared edits. Worker status becomes READY FOR REVIEW. Sol reviews diff, contracts and runtime evidence before accepting; it may reject even passing worker tests.
7. Orchestrator integrates accepted commits in dependency order. No parallel Git mutations in the same worktree. Reconcile conflicts, run integrated verification in a dedicated environment and return concrete repairs to the same worker chat.
8. Keep source-acquisition output and checkpoint state durable across chat compaction/interruption. A chat ending does not prove completion or stop its processes. Before retrying, inspect actual jobs, locks, worktree changes and checkpoints to avoid duplicate execution.
9. Owner steering/stop requests are relayed to affected workers; verify their execution has stopped before changing scope or cleanup. Preserve unintegrated/uncommitted work, worker chats and concise evidence.

Workers do not push the integration branch, open/merge PRs, accept scope cuts, delete other environments, change shared contracts unilaterally or install host dependencies.

## Worker brief contract

Every brief must contain:
- Role, human authorization quoted from originating prompt, orchestrator chat reference, and no-subdelegation rule.
- Actual target repository, owned worktree/branch, approved baseline SHA and specification paths.
- Task/requirement IDs, permitted files, prohibited shared edits, dependencies and frozen interface schemas.
- Observable acceptance criteria; fixture versus live-source boundaries; command/output evidence requirements.
- Unique Compose project, port range, output/state directories and resource budget.
- Handoff instructions and how to report questions/blockers or receive repairs.
- Current scope exclusions: no product feature implementation; full acquisition is not required to test fixtures.

Use self-contained briefs with concise approved context instead of cloning all unrelated conversation history. Workers verify their checkout and base before editing.

## Resource and mutable-state allocation

Proposed integration ports 8081–8083; runtime worker 18081–18083; data worker 28081–28083; verification worker 38081–38083. Check availability and configure alternatives if needed. Compose project names and named volumes include slot/run IDs. All host ports bind localhost. Do not run full stacks concurrently beyond available RAM; serialize heavy runtime tests when necessary.

B is the single writer for bulk download/history caches and source checkpoints; other agents read verified completed assets read-only or use separate fixtures. Each test suite gets separate data roots and DB volumes. Worktree separation does not isolate Docker, network rate budgets or external APIs. Only B performs full live history acquisition.

## State transitions and reviewer responsibility

PLANNED → RUNNING → READY FOR REVIEW → CHANGES REQUESTED → READY FOR REVIEW → VERIFIED; BLOCKED records the exact external dependency and needed action. Only orchestrator sets VERIFIED after checking integrated behavior. An external blocker cannot be relabeled as a pass. Do not claim a test or model setting without observable evidence.

Sol High-or-stronger performs final verification directly: inspect actual code, reproduce meaningful checks, audit provenance/completeness and exercise the clean quickstart. C's tests and Luna handoffs supply evidence but never substitute for that review. Record findings and fixes in verification.md and this registry.

Before PR: all included worker work handed off, no worker still editing the proposed code, integrated revision identified, evidence current, remaining T10 work accurately stated under approved D5. Orchestrator opens PR with file/reason table; no merge.

