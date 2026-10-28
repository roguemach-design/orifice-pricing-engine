# O-Plates engineering improvement pipeline

[Board and table](https://github.com/users/roguemach-design/projects/1).

One Issue per permanent OP-IMP-NNN identifier. Search open and closed Issues and existing PRs before creating work; preserve prior engineering decisions and evidence. Use the next unused number, never renumber/reuse. OP-IMP-001 remains **Triage** per owner decision October 28, 2026; no development authorization.

## Workflow and authorization

Whiteboard → Triage → Approved → Build → Test / Acceptance → Released / Verified.
Blocked, Deferred, Rejected / Closed are explicit dispositions.

Whiteboard/Triage capture an idea only. Owner approval must identify engineering scope before code changes. Record scope, date, owner, exclusions and acceptance criteria. Existing approval is not expanded by creating a register entry. Separate PR merge, staging deployment, production deployment and production verification milestones; a merged PR is never sufficient for Released / Verified. Link exact commits, CI, deployment IDs and acceptance evidence. Do not automatically close improvements from implementation PRs.

Categories: Pricing & Manufacturing; Customer Experience; Infrastructure & Reliability; Internal Operations / Manufacturing Control; Research & Future Concepts.

## Initial register

| ID | Issue | State | Interpretation |
| --- | --- | --- | --- |
| OP-IMP-001 | #53 | Triage | Handle-hole laser pricing; no development approval |
| OP-IMP-002 | #54 | Whiteboard | Metric/inch toggle proposal |
| OP-IMP-003 | #55 | Whiteboard | Large-diameter pricing investigation proposal |
| OP-IMP-004 | #56 | Test / Acceptance | Existing corrugated DXF implementation; reconcile physical acceptance |
| OP-IMP-005 | #57 | Test / Acceptance | Existing Haas review/download implementation; no machine release |
| OP-IMP-006 | #58 | Test / Acceptance | Existing LIVE-only analytics; consolidate verification |
| OP-IMP-007 | #59 | Test / Acceptance | Existing opt-in Journey monitor; consolidate runtime evidence |
| OP-IMP-008 | #60 | Deferred | PR #52 operational rollout, migration and automatic-worker acceptance |

PR #52 merged at 911dfe7dc919ff342bac13580a8224a254cda10d but remains operationally deferred. Keep staging API/UI/database suspended and FINAL4_AUTOMATIC_STAGING_ENABLED=false. Do not deploy #52 or run its migration, enable LIVE, change checkout mode, secrets or database settings under organization-only authorization.

## Durable repository policy

Default main and actual production integration history differ. Consult ARCHITECTURE.md before releases. Retain active deployment branches, rollback commits, release references, authorized unmerged work and protected manufacturing evidence. Reachability alone does not prove a branch disposable; check service branch references, deployed SHAs, PR dependencies and recovery requirements.

Recommended future branch rules: require a reviewed PR and the Test check on main and the production integration branch; disallow force pushes/deletion; document an owner emergency path. Apply security/branch-rule changes only as a separately reviewed configuration action. Keep existing CI and deployment controls.

Use organization-only PRs for docs/templates; never combine production feature work or automatic deployment with housekeeping. No paid project-management tool is needed.
