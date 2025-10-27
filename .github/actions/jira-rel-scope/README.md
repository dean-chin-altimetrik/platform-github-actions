# Jira REL-SCOPE checker action

Usage

This composite action supports two modes for working with Jira REL-SCOPE tickets:

1. **Upsert mode**: Validates a Jira issue is type `REL-SCOPE`, parses the ADF description table, and can add/update a row for a Component/Branch.
2. **Lookup mode**: Searches for REL-SCOPE tickets in a specific project and state, then validates if a component exists with the correct release branch.
3. **Validate-Upsert-Prereqs mode**: Checks all prerequisites for upsert operations without performing the upsert. Useful for early validation before branch creation.
4. **Get-State mode**: Retrieves the current status of a Jira ticket for workflow logic.

## Commands

### Upsert Command

Adds or updates a component in a specific Jira ticket.

**Inputs:**

- `command`: `"upsert"`
- `jira_key` (required): Jira issue key (e.g., `REL-1234`).
- `component` (required): Component name to add/upsert.
- `branch_name` (required): Branch name for the component.
- `issuetype` (optional): Jira issue type to validate (default: `REL-SCOPE`).
- `upsert_permission_field_id` (optional): Custom field ID that controls whether component upserting is allowed (default: `customfield_15850`). Field name will be fetched automatically from Jira.
- `blocked_statuses` (optional): JIRA statuses that should block upsert operations (default: `APPROVED CLOSED`).

**Example (uses default permission field):**

```yaml
- name: Upsert component in REL-SCOPE ticket
  uses: ./.github/actions/jira-rel-scope
  with:
    command: upsert
    jira_key: ${{ inputs.jira_key }}
    component: ${{ inputs.component }}
    branch_name: ${{ inputs.branch_name }}
    # upsert_permission_field_id defaults to "customfield_15850"
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

**Example with custom permission field:**

```yaml
- name: Upsert component with custom permission field
  uses: ./.github/actions/jira-rel-scope
  with:
    command: upsert
    jira_key: ${{ inputs.jira_key }}
    component: ${{ inputs.component }}
    branch_name: ${{ inputs.branch_name }}
    upsert_permission_field_id: "customfield_12345"
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

**Example with custom blocked statuses:**

```yaml
- name: Upsert component with custom blocked statuses
  uses: ./.github/actions/jira-rel-scope
  with:
    command: upsert
    jira_key: ${{ inputs.jira_key }}
    component: ${{ inputs.component }}
    branch_name: ${{ inputs.branch_name }}
    blocked_statuses: "APPROVED CLOSED RESOLVED"
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}
```

### Validate-Upsert-Prereqs Command

Checks all prerequisites for upsert operations without performing the actual upsert. Use this before creating branches to ensure the upsert will succeed.

**Inputs:**

- `command`: `"validate-upsert-prereqs"`
- `jira_key` (required): Jira issue key (e.g., `REL-1234`).
- `component` (optional): Component name to check for conflicts. If provided, validates that the component doesn't already exist in the table.
- `branch_name` (optional): Branch name (optional for validation).
- `issuetype` (optional): Jira issue type to validate (default: `REL-SCOPE`).
- `upsert_permission_field_id` (optional): Custom field ID that controls whether component upserting is allowed (default: `customfield_15850`). Field name will be fetched automatically from Jira.
- `blocked_statuses` (optional): JIRA statuses that should block upsert operations (default: `APPROVED CLOSED`).

**Validation Checks Performed:**
- Issue type matches expected type
- Upsert permission field is set to "Allowed"
- Ticket status is not in blocked statuses
- Component does not already exist in the table (if component provided)

**Example:**

```yaml
- name: Validate upsert prerequisites
  id: validate
  uses: ./.github/actions/jira-rel-scope
  with:
    command: validate-upsert-prereqs
    jira_key: ${{ inputs.jira_key }}
    component: "my-component"  # Optional: checks for conflicts
    branch_name: "feature/my-branch"  # Optional
  env:
    JIRA_BASE_URL: ${{ secrets.JIRA_BASE_URL }}
    JIRA_EMAIL: ${{ secrets.JIRA_EMAIL }}
    JIRA_API_TOKEN: ${{ secrets.JIRA_API_TOKEN }}

- name: Create branch only if validation passed
  if: steps.validate.outputs.validation_passed == 'true'
  run: |
    git checkout -b feature/my-branch
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
