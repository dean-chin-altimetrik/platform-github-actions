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
