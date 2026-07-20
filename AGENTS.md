# Engineering Workflow

Apply this workflow to every material change:

1. Scope the affected behavior and runtime contract.
2. Make the smallest production-safe implementation change.
3. Run focused validation and review the diff for regressions.
4. Review `README.md` against the current implementation, configuration, runtime behavior, and validation evidence. Update it whenever any of those facts have changed or are stale.
5. Commit and push the implementation and its README update together on a dedicated `AnkanCodes/` branch. Do not claim a push succeeded without verifying the remote branch.

Keep README statements factual and current. Do not retain dated test counts, deployment claims, source counts, or operational behavior that cannot be supported by the current code or a recorded validation run.
