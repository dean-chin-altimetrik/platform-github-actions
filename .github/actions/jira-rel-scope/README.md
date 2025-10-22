Jira REL-SCOPE checker action

Usage

This composite action validates a Jira issue is type `REL-SCOPE`, parses the ADF description table, and can add a row for a Component/Branch.

Inputs

- `jira_key` (required): Jira issue key (e.g., `REL-1234`).
- `component` (required): Component name to add/upsert.
- `branch_name` (required): Branch name for the component.

Example (workflow)

```yaml
- name: Check REL-SCOPE in Jira
  uses: ./.github/actions/jira-rel-scope
  with:
    jira_key: ${{ inputs.jira_key }}
    component: ${{ inputs.component }}
    branch_name: ${{ inputs.branch_name }}
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

Notes

- The action will modify Jira only if the environment variable `SKIP_JIRA_UPDATE` is not set and the runner has proper API permissions. By default this action runs read-only unless credentials are provided and the script performs the update.
- The older `--upsert-row` style argument was removed in favor of explicit `component` and `branch_name` inputs.

Secrets

- This action requires three secrets to access Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`.
- When a workflow in another repository calls this action (via `owner/repo/path@ref`), the action runs in the caller's workflow context and cannot read secrets stored only in the action repository. That means the caller repo (or the organization) must provide these secrets.

Example (repository secrets)

```yaml
env:
  JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
  JIRA_EMAIL:    ${{ secrets.JIRA_EMAIL }}
  JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

Alternatively, create organization-level secrets and grant the caller repository access to avoid adding the secrets to every repo individually.
