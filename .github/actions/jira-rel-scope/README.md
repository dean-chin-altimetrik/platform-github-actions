# Jira REL-SCOPE checker action

Usage

This composite action supports two modes for working with Jira REL-SCOPE tickets:

1. **Upsert mode**: Validates a Jira issue is type `REL-SCOPE`, parses the ADF description table, and can add/update a row for a Component/Branch.
2. **Lookup mode**: Searches for REL-SCOPE tickets in a specific project and state, then validates if a component exists with the correct release branch.

## Commands

### Upsert Command

Adds or updates a component in a specific Jira ticket.

**Inputs:**

- `command`: `"upsert"`
- `jira_key` (required): Jira issue key (e.g., `REL-1234`).
- `component` (required): Component name to add/upsert.
- `branch_name` (required): Branch name for the component.
- `issuetype` (optional): Jira issue type to validate (default: `REL-SCOPE`).

**Example:**

```yaml
- name: Upsert component in REL-SCOPE ticket
  uses: ./.github/actions/jira-rel-scope
  with:
    command: upsert
    jira_key: ${{ inputs.jira_key }}
    component: ${{ inputs.component }}
    branch_name: ${{ inputs.branch_name }}
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

### Lookup Command

Searches for a component in REL-SCOPE tickets and validates the release branch.

**Inputs:**

- `command`: `"lookup"`
- `project` (required): Jira project key to search in.
- `state` (required): Jira state/status to filter by.
- `component` (required): Component name to search for.
- `release_branch` (required): Expected release branch for the component.
- `issuetype` (optional): Jira issue type to search for (default: `REL-SCOPE`).

**Example:**

```yaml
- name: Lookup component in REL-SCOPE tickets
  uses: ./.github/actions/jira-rel-scope
  with:
    command: lookup
    project: "PROJ"
    state: "In Progress"
    component: "my-component"
    release_branch: "release/v1.0"
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

**Example with custom issue type:**

```yaml
- name: Lookup component in custom issue type
  uses: ./.github/actions/jira-rel-scope
  with:
    command: lookup
    project: "PROJ"
    state: "Active Env"
    component: "my-component"
    release_branch: "release/v1.0"
    issuetype: "REL-SCOPE"
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

## Lookup Error Scenarios

The lookup command will fail the pipeline with detailed error messages for:

- **No tickets found**: No REL-SCOPE tickets in the specified project/state
- **Multiple tickets found**: Multiple tickets found (lists all with keys and summaries)
- **Component not found**: Component doesn't exist in the found ticket (shows available components)
- **Wrong branch**: Component found but release branch doesn't match (shows expected vs actual)

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
