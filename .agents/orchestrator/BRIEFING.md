# BRIEFING — 2026-06-16T00:52:00+07:00

## Mission
Merancang dan membangun purwarupa (prototype) sistem trading berbasis kecerdasan buatan (AI) yang terintegrasi dengan bursa BingX, tanpa menyentuh modul botreding yang sudah ada.

## 🔒 My Identity
- Archetype: Project Orchestrator
- Roles: orchestrator, user_liaison, human_reporter, successor
- Working directory: /Users/mac/sinyalbingx/.agents/orchestrator
- Original parent: top-level
- Original parent conversation ID: 97ccebe7-58b3-4ea2-9ac6-8d79a7800d4e

## 🔒 My Workflow
- **Pattern**: Project
- **Scope document**: /Users/mac/sinyalbingx/.agents/orchestrator/PROJECT.md
1. **Decompose**: Decompose requirements into milestones (Explorer, Worker, Reviewer, Challenger, Auditor).
2. **Dispatch & Execute** (pick ONE):
   - **Delegate (sub-orchestrator)**: [TBD]
3. **On failure** (in this order):
   - Retry: nudge stuck agent or re-send task
   - Replace: spawn fresh agent with partial progress
   - Skip: proceed without (only if non-critical)
   - Redistribute: split stuck agent's remaining work
   - Redesign: re-partition decomposition
   - Escalate: report to parent (sub-orchestrators only, last resort)
4. **Succession**: at 16 spawns, write handoff.md, spawn successor
- **Work items**:
  1. Assess and Decompose Project [done]
  2. Milestone 1: Assess & Explore [done]
  3. Milestone 2: Implementation Check [in-progress]
- **Current phase**: 3
- **Current focus**: Milestone 2: Implement mitigations and check integration

## 🔒 Key Constraints
- Never write, modify, or create source code files directly.
- Never run build/test commands yourself — require workers to do so.
- Forensic Auditor reports INTEGRITY VIOLATION -> milestone fails.
- Do not modify files in the botreding directory.
- Main agent / parent ID for communication is 7064893c-dea4-4795-bd20-3ab54801f3da.

## Current Parent
- Conversation ID: 97ccebe7-58b3-4ea2-9ac6-8d79a7800d4e
- Updated: not yet

## Key Decisions Made
- Use Project Orchestrator pattern.
- Place all AI filter code in `ai_trading/` and integrate with webhook server.

## Team Roster
| Agent | Type | Work Item | Status | Conv ID |
|-------|------|-----------|--------|---------|
| explorer_1 | teamwork_preview_explorer | Analisis keandalan codebase | completed | 0fe92468-7f30-43b4-a8cc-15edd7b92adc |
| explorer_2 | teamwork_preview_explorer | Verifikasi kesesuaian persyaratan | completed | 2cf0f855-2217-47db-b138-a11c22b64ea9 |
| explorer_3 | teamwork_preview_explorer | Analisis integritas data dan .env | completed | e7a95981-7e98-461b-a3fe-394c6a35d129 |
| worker_m2 | teamwork_preview_worker | Implementasi perbaikan dan mitigasi | completed | 4a6ab5e9-bc23-4e99-9845-464e54000636 |
| reviewer_m2_1 | teamwork_preview_reviewer | Tinjauan logika & keamanan 1 | in-progress | b1adfe1c-84b9-4a06-b95b-e36adf5a39f9 |
| reviewer_m2_2 | teamwork_preview_reviewer | Tinjauan logika & keamanan 2 | in-progress | 83475e48-770e-4f77-9d48-baa4c739a373 |
| challenger_m2_1 | teamwork_preview_challenger | Verifikasi empiris & stress-testing 1 | in-progress | 86dcf056-d8cd-442d-a829-38c095035cc2 |
| challenger_m2_2 | teamwork_preview_challenger | Verifikasi empiris & stress-testing 2 | in-progress | 9e108c23-0cec-48ac-ab3a-4133eafd6fe4 |
| auditor_m2 | teamwork_preview_auditor | Audit forensik no-cheating | in-progress | 748432b8-b6a7-48b2-a007-2af69ebb8c54 |

## Succession Status
- Succession required: no
- Spawn count: 9 / 16
- Pending subagents: b1adfe1c-84b9-4a06-b95b-e36adf5a39f9, 83475e48-770e-4f77-9d48-baa4c739a373, 86dcf056-d8cd-442d-a829-38c095035cc2, 9e108c23-0cec-48ac-ab3a-4133eafd6fe4, 748432b8-b6a7-48b2-a007-2af69ebb8c54
- Predecessor: none
- Successor: not yet spawned

## Active Timers
- Heartbeat cron: 97ccebe7-58b3-4ea2-9ac6-8d79a7800d4e/task-33
- Safety timer: none
- On succession: kill all timers incentives before spawning successor
- On context truncation: run `manage_task(Action="list")` — re-create if missing

## Artifact Index
- /Users/mac/sinyalbingx/.agents/orchestrator/PROJECT.md — Project Roadmap and Milestones
- /Users/mac/sinyalbingx/.agents/orchestrator/progress.md — Status Tracking Heartbeat
- /Users/mac/sinyalbingx/.agents/orchestrator/ORIGINAL_REQUEST.md — Verbatim Request
