#!/usr/bin/env python3
import argparse
import json
import os
import sys
import requests
from tabulate import tabulate


def die(msg, status=1):
    # Surface the error in multiple places:
    # 1) GitHub Actions error annotation (visible in workflow UI)
    # 2) stderr (for logs)
    # 3) GITHUB_OUTPUT as `error_message` so workflows can read it as an output
    # 4) step summary for quick visibility in the job UI
    print(f"::error::{msg}", file=sys.stdout)
    print(f"ERROR: {msg}", file=sys.stderr)
    try:
        write_output("error_message", str(msg))
    except Exception:
        pass
    try:
        append_summary(f"**ERROR:** {msg}")
    except Exception:
        pass
    sys.exit(status)


def jira_get_issue(base, email, token, key, custom_field_id=None):
    url = f"{base}/rest/api/3/issue/{key}"
    # Also request `summary` and `status` so we can include the issue title and status in the check summary
    fields = "issuetype,description,summary,status"
    if custom_field_id:
        fields += f",{custom_field_id}"
    params = {"fields": fields}
    r = requests.get(
        url, params=params, auth=(email, token), headers={"Accept": "application/json"}
    )
    if r.status_code == 404:
        die(f"Jira issue not found: {key}")
    if r.status_code >= 300:
        die(f"Jira API error {r.status_code}: {r.text[:500]}")
    return r.json()


def walk_adf_tables(node, found):
    """Recursively find ADF tables in Jira description (Atlassian Document Format)."""
    if isinstance(node, dict):
        if node.get("type") == "table":
            found.append(node)
        for k, v in node.items():
            walk_adf_tables(v, found)
    elif isinstance(node, list):
        for item in node:
            walk_adf_tables(item, found)


def adf_table_to_rows(table_node):
    """
    Convert ADF table to header + rows.
    ADF table structure: table -> tableRow[] -> tableHeader[] / tableCell[]
    """
    rows = table_node.get("content", []) or []
    headers = []
    data = []
    for idx, row in enumerate(rows):
        cells = row.get("content", []) or []
        row_vals = []
        is_header_row = (
            all(c.get("type") == "tableHeader" for c in cells) and len(cells) > 0
        )
        for cell in cells:
            # Extract plain text from cell content nodes
            txt_parts = []
            for c in cell.get("content", []) or []:
                txt_parts.append(extract_text(c))
            row_vals.append("".join(txt_parts).strip())
        if idx == 0 and is_header_row:
            headers = row_vals
        else:
            data.append(row_vals)
    # normalize column widths across rows
    width = max(len(headers), max((len(r) for r in data), default=0))
    headers = (
        (headers + [""] * (width - len(headers)))
        if headers
        else [f"Col{i + 1}" for i in range(width)]
    )
    data = [r + [""] * (width - len(r)) for r in data]
    return headers, data


def extract_text(node):
    """Best-effort text extraction from ADF nodes."""
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    if t == "text":
        return node.get("text", "")
    # inline marks (bold, link, etc.) -> recurse on content if any
    txt = ""
    for k in ("text",):  # fallback
        if k in node and isinstance(node[k], str):
            txt += node[k]
    for child_key in ("content",):
        if child_key in node and isinstance(node[child_key], list):
            for ch in node[child_key]:
                txt += extract_text(ch)
    return txt


def write_output(k, v):
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        # If value contains a newline, use the GitHub Actions multiline value
        # syntax to avoid the runner rejecting the output (it expects a specific
        # heredoc format when values include newlines).
        if isinstance(v, str) and "\n" in v:
            # Choose a delimiter that's unlikely to appear in the value.
            delim = "EOF"
            # If EOF appears in the value, append a random numeric suffix.
            if delim in v:
                import time

                delim = f"EOF_{int(time.time())}"
            f.write(f"{k}<<{delim}\n")
            f.write(v)
            # Ensure the final line break before delimiter
            if not v.endswith("\n"):
                f.write("\n")
            f.write(f"{delim}\n")
        else:
            f.write(f"{k}={v}\n")


def append_summary(md):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(md + "\n")


def jira_get_field_metadata(base, email, token, field_id):
    """Get custom field metadata including the friendly name."""
    url = f"{base}/rest/api/3/field"
    r = requests.get(url, auth=(email, token), headers={"Accept": "application/json"})
    if r.status_code >= 300:
        die(f"Jira field metadata API error {r.status_code}: {r.text[:500]}")

    fields = r.json()
    for field in fields:
        if field.get("id") == field_id:
            return field.get("name", field_id)

    # If field not found, return the field_id as fallback
    return field_id


def validate_upsert_prerequisites(
    base,
    email,
    token,
    jira_key,
    upsert_permission_field_id,
    blocked_statuses,
    issuetype,
):
    """
    Validate all prerequisites for upsert operation.
    Returns a dict with validation results and details.
    """
    validation_result = {"valid": True, "errors": [], "warnings": [], "details": {}}

    # Get the issue
    issue = jira_get_issue(base, email, token, jira_key, upsert_permission_field_id)
    fields = issue.get("fields", {})

    # Get basic fields
    issuetype_name = (fields.get("issuetype") or {}).get("name", "")
    issue_summary = (fields.get("summary") or "").strip()
    current_status = (fields.get("status") or {}).get("name", "")

    validation_result["details"]["issue_type"] = issuetype_name
    validation_result["details"]["issue_summary"] = issue_summary
    validation_result["details"]["current_status"] = current_status

    # Validate issue type
    if issuetype_name != issuetype:
        validation_result["valid"] = False
        validation_result["errors"].append(
            f"Issue {jira_key} is not of type {issuetype} (current: {issuetype_name})"
        )

    # Check upsert permission field if provided
    if upsert_permission_field_id:
        field_name = jira_get_field_metadata(
            base, email, token, upsert_permission_field_id
        )
        validation_result["details"]["permission_field_name"] = field_name

        permission_field_value = fields.get(upsert_permission_field_id)
        if permission_field_value is None:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Upsert permission field '{field_name}' ({upsert_permission_field_id}) is not accessible or does not exist"
            )
        else:
            if isinstance(permission_field_value, dict):
                field_value = permission_field_value.get("value", "")
            else:
                field_value = str(permission_field_value)

            validation_result["details"]["permission_field_value"] = field_value

            if field_value.strip().lower() != "allowed":
                validation_result["valid"] = False
                validation_result["errors"].append(
                    f"Upsert permission field '{field_name}' is not set to 'Allowed' (current value: '{field_value}')"
                )

    # Check ticket status
    if blocked_statuses:
        if current_status.upper() in [s.upper() for s in blocked_statuses]:
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Ticket is in '{current_status}' status. Blocked statuses: {', '.join(blocked_statuses)}"
            )

    return validation_result


def jira_search_issues(base, email, token, jql, fields=None):
    """Search for Jira issues using JQL."""
    if fields is None:
        fields = ["key", "summary", "issuetype", "status", "description"]

    url = f"{base}/rest/api/3/search/jql"
    params = {
        "jql": jql,
        "fields": ",".join(fields),
        "maxResults": 100,  # Adjust as needed
    }
    r = requests.get(
        url, params=params, auth=(email, token), headers={"Accept": "application/json"}
    )
    if r.status_code >= 300:
        die(f"Jira search API error {r.status_code}: {r.text[:500]}")
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--command",
        choices=["upsert", "lookup", "get-state", "validate-upsert-prereqs"],
        required=True,
        help="Command to execute: 'upsert' to add/update component, 'lookup' to search for component, 'get-state' to retrieve ticket status, 'validate-upsert-prereqs' to check upsert prerequisites",
    )

    # Common parameters
    ap.add_argument(
        "--component",
        required=False,
        help="Component name to add/update or search for (required for upsert and lookup commands)",
    )
    ap.add_argument(
        "--issuetype",
        default="REL-SCOPE",
        help="Jira issue type to search for (default: REL-SCOPE)",
    )

    # Upsert mode parameters
    ap.add_argument(
        "--jira-key", help="Specific Jira key to process (required for upsert mode)"
    )
    ap.add_argument(
        "--branch-name", help="Branch name for the component (required for upsert mode)"
    )
    ap.add_argument(
        "--upsert-permission-field-id",
        help="Custom field ID that controls whether component upserting is allowed (e.g., customfield_15850). Field name will be fetched automatically from Jira.",
    )
    ap.add_argument(
        "--blocked-statuses",
        nargs="+",  # Accept multiple values
        default=["APPROVED", "CLOSED"],
        help="JIRA statuses that should block upsert operations (default: APPROVED CLOSED)",
    )

    # Lookup mode parameters
    ap.add_argument(
        "--project", help="Jira project key to search in (required for lookup mode)"
    )
    ap.add_argument(
        "--state", help="Jira state/status to filter by (required for lookup mode)"
    )
    ap.add_argument(
        "--release-branch",
        help="Release branch to search for in component table (required for lookup mode)",
    )

    args = ap.parse_args()

    # Validate arguments based on command
    if args.command == "upsert":
        if not args.jira_key or not args.branch_name or not args.component:
            die(
                "Upsert command requires --jira-key, --branch-name, and --component arguments"
            )
    elif args.command == "lookup":
        if (
            not args.project
            or not args.state
            or not args.release_branch
            or not args.component
        ):
            die(
                "Lookup command requires --project, --state, --release-branch, and --component arguments"
            )
    elif args.command == "get-state":
        if not args.jira_key:
            die("Get-state command requires --jira-key argument")
    elif args.command == "validate-upsert-prereqs":
        if not args.jira_key:
            die("Validate-upsert-prereqs command requires --jira-key argument")

    base = os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_EMAIL") or "dean.chin@altimetrik.com"
    token = os.getenv("JIRA_API_TOKEN")
    # JIRA_EMAIL is optional and defaults to dean.chin@altimetrik.com
    missing = [
        name
        for name, val in (
            ("JIRA_BASE_URL", base),
            ("JIRA_API_TOKEN", token),
        )
        if not val
    ]
    if missing:
        die(
            "Missing JIRA credentials in environment: "
            + ", ".join(missing)
            + ".\nProvide these as repository or organization secrets and pass them to the workflow (example in README)."
        )

    # Handle get-state command
    if args.command == "get-state":
        # Fetch the ticket and return its status
        issue = jira_get_issue(
            base, email, token, args.jira_key, args.upsert_permission_field_id
        )
        fields = issue.get("fields", {})
        current_status = (fields.get("status") or {}).get("name", "")
        issue_summary = (fields.get("summary") or "").strip()

        # Write outputs for workflow consumption
        write_output("ticket_status", current_status)
        write_output("ticket_key", args.jira_key)
        write_output("ticket_summary", issue_summary)

        # Generate summary
        summary_parts = [
            f"### Get State: **{args.jira_key}**{(' — ' + issue_summary) if issue_summary else ''}",
            f"- Current status: **{current_status}**",
        ]

        append_summary("\n".join(summary_parts))
        print("\n".join(summary_parts))

        return

    # Handle validate-upsert-prereqs command
    if args.command == "validate-upsert-prereqs":
        # Run validation checks
        validation = validate_upsert_prerequisites(
            base,
            email,
            token,
            args.jira_key,
            args.upsert_permission_field_id,
            args.blocked_statuses,
            args.issuetype,
        )

        # Write outputs
        write_output("validation_passed", str(validation["valid"]).lower())
        write_output("ticket_status", validation["details"].get("current_status", ""))
        write_output("ticket_key", args.jira_key)

        # Generate summary
        summary_parts = [
            f"### Validation Results: **{args.jira_key}**",
            f"- **{'✅ Validation Passed' if validation['valid'] else '❌ Validation Failed'}**",
        ]

        if validation["details"].get("issue_summary"):
            summary_parts.append(f"- Summary: {validation['details']['issue_summary']}")
        summary_parts.append(
            f"- Type: {validation['details'].get('issue_type', 'Unknown')}"
        )
        summary_parts.append(
            f"- Status: {validation['details'].get('current_status', 'Unknown')}"
        )

        if validation["details"].get("permission_field_name"):
            summary_parts.append(
                f"- Permission Field: {validation['details']['permission_field_name']}"
            )
            summary_parts.append(
                f"- Permission Value: {validation['details'].get('permission_field_value', 'Unknown')}"
            )

        if validation["errors"]:
            summary_parts.append("\n**❌ Validation Errors:**")
            for error in validation["errors"]:
                summary_parts.append(f"- {error}")

        append_summary("\n".join(summary_parts))
        print("\n".join(summary_parts))

        # Fail the workflow if validation didn't pass
        if not validation["valid"]:
            error_msg = "Validation failed: " + "; ".join(validation["errors"])
            die(error_msg)

        return

    # Handle lookup command
    if args.command == "lookup":
        # Search for tickets of specified type in the specified project and state
        jql = f'project = "{args.project}" AND issuetype = "{args.issuetype}" AND status = "{args.state}"'
        search_result = jira_search_issues(base, email, token, jql)
        issues = search_result.get("issues", [])

        # Check if there's exactly one ticket
        if len(issues) == 0:
            error_msg = f"❌ No {args.issuetype} tickets found in project '{args.project}' with state '{args.state}'"
            append_summary(f"**{error_msg}**")
            die(error_msg)
        elif len(issues) > 1:
            # Create detailed error message with ticket summaries
            ticket_list = []
            for issue in issues:
                summary = issue.get("fields", {}).get("summary", "No summary")
                ticket_list.append(f"- **{issue['key']}**: {summary}")

            error_msg = f"❌ Multiple {args.issuetype} tickets found in project '{args.project}' with state '{args.state}':"
            detailed_msg = f"{error_msg}\n\nFound {len(issues)} tickets:\n" + "\n".join(
                ticket_list
            )
            append_summary(
                f"**{error_msg}**\n\nFound {len(issues)} tickets:\n"
                + "\n".join(ticket_list)
            )
            die(detailed_msg)

        # Get the single ticket
        issue = issues[0]
        issue_key = issue["key"]
        write_output("found_ticket_key", issue_key)

        # Process the ticket's table to look for the component and release branch
        fields = issue.get("fields", {})
        desc = fields.get("description")
        has_description = bool(desc)
        write_output("has_description", str(has_description).lower())

        headers, rows = [], []
        if desc:
            tables = []
            walk_adf_tables(desc, tables)
            if tables:
                headers, rows = adf_table_to_rows(tables[0])
        has_table = bool(headers or rows)
        write_output("has_table", str(has_table).lower())

        # Look for the specific component and release branch
        component_found = False
        branch_matches = False
        matching_row = None
        found_component_row = (
            None  # Track the row with the component (even if branch doesn't match)
        )

        if has_table:
            # Look for component in the table (assuming Component is column index 1, Branch Name is column index 2)
            comp_idx = 1
            branch_idx = 2

            for r in rows:
                if (
                    len(r) > comp_idx
                    and (r[comp_idx] or "").strip().lower()
                    == args.component.strip().lower()
                ):
                    component_found = True
                    found_component_row = r
                    # Check if the branch matches
                    if (
                        len(r) > branch_idx
                        and (r[branch_idx] or "").strip() == args.release_branch.strip()
                    ):
                        branch_matches = True
                        matching_row = r
                    break

        write_output("component_found", str(component_found).lower())
        write_output("branch_matches", str(branch_matches).lower())
        write_output("matching_row_json", matching_row or [])

        # Generate summary
        summary_parts = [
            f"### Lookup Results for Project: **{args.project}**",
            f"- State: **{args.state}**",
            f"- Component: **{args.component}**",
            f"- Release Branch: **{args.release_branch}**",
            f"- Found ticket: **{issue_key}**",
            f"- Component found: **{component_found}**",
            f"- Branch matches: **{branch_matches}**",
        ]

        if has_table:
            summary_parts.append("\n**Table in found ticket:**\n")
            summary_parts.append(tabulate(rows, headers=headers, tablefmt="github"))

        if matching_row:
            summary_parts.append("\n**✅ Matching row:**\n")
            summary_parts.append(
                tabulate([matching_row], headers=headers, tablefmt="github")
            )
        elif found_component_row:
            summary_parts.append("\n**⚠️ Component found but branch doesn't match:**\n")
            summary_parts.append(
                tabulate([found_component_row], headers=headers, tablefmt="github")
            )

        # Append the summary
        append_summary("\n".join(summary_parts))
        print("\n".join(summary_parts))

        # Exit with appropriate status and detailed error messages
        if not component_found:
            if not has_table:
                error_msg = f"❌ Component '{args.component}' not found in ticket {issue_key} - ticket has no table"
            else:
                error_msg = (
                    f"❌ Component '{args.component}' not found in ticket {issue_key}"
                )
                error_msg += "\n\n**Available components in the table:**\n"
                if rows:
                    # Show all components from the table
                    comp_names = []
                    for r in rows:
                        if len(r) > comp_idx and r[comp_idx].strip():
                            comp_names.append(f"- {r[comp_idx].strip()}")
                    if comp_names:
                        error_msg += "\n".join(comp_names)
                    else:
                        error_msg += "- No components found in table"
                else:
                    error_msg += "- Table is empty"
            die(error_msg)

        if not branch_matches:
            actual_branch = (
                found_component_row[branch_idx].strip()
                if len(found_component_row) > branch_idx
                else "Not specified"
            )
            error_msg = f"❌ Component '{args.component}' found in ticket {issue_key} but release branch does not match"
            error_msg += f"\n\n**Expected:** `{args.release_branch}`"
            error_msg += f"\n**Actual:** `{actual_branch}`"
            error_msg += "\n\n**Component row details:**\n"
            error_msg += tabulate(
                [found_component_row], headers=headers, tablefmt="github"
            )
            die(error_msg)

        # Success - both component and branch match
        write_output("lookup_result", "success")
        return

    # Upsert mode logic - reuse validation function
    validation = validate_upsert_prerequisites(
        base,
        email,
        token,
        args.jira_key,
        args.upsert_permission_field_id,
        args.blocked_statuses,
        args.issuetype,
    )

    # Fail early if validation doesn't pass (same checks as validate command)
    if not validation["valid"]:
        error_msg = "Upsert validation failed: " + "; ".join(validation["errors"])
        die(error_msg)

    # Get issue details for upsert processing
    issue = jira_get_issue(
        base, email, token, args.jira_key, args.upsert_permission_field_id
    )
    fields = issue.get("fields", {})
    issuetype = (fields.get("issuetype") or {}).get("name", "")
    issue_summary = (fields.get("summary") or "").strip()
    is_correct_type = issuetype == args.issuetype
    write_output("is_correct_type", str(is_correct_type).lower())

    # Check upsert permission field if provided
    upsert_permission_allowed = True
    if args.upsert_permission_field_id:
        # Get the friendly name of the custom field
        field_name = jira_get_field_metadata(
            base, email, token, args.upsert_permission_field_id
        )

        permission_field_value = fields.get(args.upsert_permission_field_id)
        if permission_field_value is None:
            # Field doesn't exist or is not accessible
            die(
                f"Upsert permission field '{field_name}' ({args.upsert_permission_field_id}) is not accessible or does not exist"
            )
        elif isinstance(permission_field_value, dict):
            # Handle select list fields (common format)
            field_value = permission_field_value.get("value", "")
        else:
            # Handle simple string fields
            field_value = str(permission_field_value)

        upsert_permission_allowed = field_value.strip().lower() == "allowed"
        if not upsert_permission_allowed:
            die(
                f"Upsert permission field '{field_name}' is not set to 'Allowed' (current value: '{field_value}'), so we can't upsert the component"
            )

    write_output("upsert_permission_allowed", str(upsert_permission_allowed).lower())

    # Check ticket status if blocked statuses are provided
    current_status = (fields.get("status") or {}).get("name", "")
    status_allows_upsert = True
    if args.blocked_statuses:
        if current_status.upper() in [
            status.upper() for status in args.blocked_statuses
        ]:
            die(
                f"Upsert blocked: Ticket {args.jira_key} is in '{current_status}' status. Blocked statuses: {', '.join(args.blocked_statuses)}"
            )
        status_allows_upsert = current_status.upper() not in [
            s.upper() for s in args.blocked_statuses
        ]

    write_output("ticket_status", current_status)
    write_output("status_allows_upsert", str(status_allows_upsert).lower())

    desc = fields.get("description")
    has_description = bool(desc)
    write_output("has_description", str(has_description).lower())

    headers, rows = [], []
    if desc:
        tables = []
        walk_adf_tables(desc, tables)
        if tables:
            headers, rows = adf_table_to_rows(tables[0])
    has_table = bool(headers or rows)
    write_output("has_table", str(has_table).lower())

    matched_rows = rows

    # Render tables (full + matched)
    full_tbl_md = ""
    if has_table:
        full_tbl_md = tabulate(rows, headers=headers, tablefmt="github")

    # Collect upsert-specific summary lines here; we'll build the final
    # summary after upsert processing so the Full table shows the
    # post-upsert state.
    upsert_summary = []

    # Outputs
    write_output("table_markdown", full_tbl_md)
    write_output("matched_rows_json", matched_rows)

    # Upsert logic: if requested, add or update a row in the table and push back
    # (Note: this action currently only writes outputs; updating Jira would require API write permissions.)
    # Build upsert CSV from the provided component and branch-name (other fields empty).
    upsert_raw = ""
    if args.component or args.branch_name:
        comp = args.component.strip()
        branch = args.branch_name.strip()
        # CSV format expected by the upsert logic: Component, Branch Name, Change Request, External Dependency
        upsert_raw = ",".join([comp, branch, "", ""]).strip()
    if upsert_raw:
        # Expected headers
        expected_headers = [
            "Order",
            "Component",
            "Branch Name",
            "Change Request",
            "External Dependency",
        ]

        # If no table exists, create one with expected headers
        if not has_table:
            headers = expected_headers.copy()
            rows = []
            has_table = True

        # Validate headers exactly (case-insensitive comparison of normalized names)
        norm_hdrs = [h.strip().lower() for h in headers]
        norm_expected = [h.strip().lower() for h in expected_headers]
        if norm_hdrs != norm_expected:
            # Fail and provide expected header information
            msg = (
                "Table headers do not match expected schema. Expected headers: "
                + ", ".join(expected_headers)
            )
            write_output("error_message", msg)
            append_summary(f"**ERROR:** {msg}")
            die(msg)

        # Parse upsert values: Component, Branch Name, Change Request, External Dependency
        parts = [p.strip() for p in upsert_raw.split(",")]
        if len(parts) < 1:
            die(
                "Component value is required (provide --component and --branch-name inputs)"
            )

        comp = parts[0]
        branch = parts[1] if len(parts) > 1 else ""
        change_req = parts[2] if len(parts) > 2 else ""
        ext_dep = parts[3] if len(parts) > 3 else ""

        # Case-insensitive search for Component in existing rows (Component is column index 1)
        comp_idx = 1
        found = False
        old_row = None
        for r in rows:
            if (
                len(r) > comp_idx
                and (r[comp_idx] or "").strip().lower() == comp.strip().lower()
            ):
                # capture a copy of the old row for reporting
                old_row = r.copy()
                # Do NOT overwrite existing row — fail with clear outputs so user knows why.
                msg = (
                    f"Upsert aborted: Component '{comp}' already exists in table (Order {old_row[0]}). "
                    "This action is configured not to overwrite existing rows."
                )
                write_output("upsert_result", "conflict")
                write_output("upsert_conflict_row_json", old_row)
                write_output("error_message", msg)
                append_summary(f"**ERROR:** {msg}")
                die(msg)
        if not found:
            # Determine next Order value
            try:
                max_order = max(
                    (int(r[0]) for r in rows if r and r[0] != ""), default=-1
                )
            except Exception:
                max_order = len(rows) - 1
            new_order = max_order + 1 if max_order >= 0 else 0
            new_row = [str(new_order), comp, branch, change_req, ext_dep]
            rows.append(new_row)

        # Prepare human-friendly upsert report and append to upsert_summary
        upsert_summary.append("\n**Upsert result:**\n")
        if old_row is not None:
            # Updated existing row: show before/after
            upsert_summary.append(
                f"- Updated Component **{comp}** (Order {old_row[0]}):\n"
            )
            # render small markdown table showing before and after
            before_tbl = tabulate([old_row], headers=headers, tablefmt="github")
            after_row = None
            # find the updated row (match by order)
            for rr in rows:
                if rr and rr[0] == old_row[0]:
                    after_row = rr
                    break
            after_tbl = (
                tabulate([after_row], headers=headers, tablefmt="github")
                if after_row
                else ""
            )
            upsert_summary.append("**Before:**\n")
            upsert_summary.append(before_tbl)
            upsert_summary.append("**After:**\n")
            upsert_summary.append(after_tbl)
            # write outputs for update
            write_output("upsert_result", "updated")
            write_output("upserted_row_json", after_row)
        else:
            # Added new row: show the inserted row
            upsert_summary.append(
                f"- Added Component **{comp}** (Order {new_row[0]}):\n"
            )
            upsert_summary.append(
                tabulate([new_row], headers=headers, tablefmt="github")
            )
            # write outputs for add
            write_output("upsert_result", "added")
            write_output("upserted_row_json", new_row)

        # Re-render the table markdown and write as output
        full_tbl_md = tabulate(rows, headers=headers, tablefmt="github")
        write_output("table_markdown", full_tbl_md)
        write_output("matched_rows_json", rows)

        # Prepare ADF table node for update
        def make_text_node(s):
            return {"type": "text", "text": s}

        def make_paragraph(text):
            return {"type": "paragraph", "content": [{"type": "text", "text": text}]}

        def make_table_header_cell(text):
            # tableHeader expects content of paragraph nodes
            return {"type": "tableHeader", "content": [make_paragraph(text)]}

        def make_table_cell(text):
            # tableCell expects content of paragraph nodes
            return {"type": "tableCell", "content": [make_paragraph(text)]}

        def build_adf_table(headers_list, rows_list):
            # header row
            header_row = {
                "type": "tableRow",
                "content": [make_table_header_cell(h) for h in headers_list],
            }
            data_rows = []
            for r in rows_list:
                cells = [make_table_cell(c) for c in r]
                data_rows.append({"type": "tableRow", "content": cells})
            return {"type": "table", "content": [header_row] + data_rows}

        new_table_node = build_adf_table(headers, rows)

        # Function to replace first table node in ADF description (in-place) or append if not found
        def replace_or_append_first_table(adf_desc, new_table):
            # If no description or non-dict, create a doc wrapper
            if not adf_desc or not isinstance(adf_desc, dict):
                return {"type": "doc", "version": 1, "content": [new_table]}, True

            replaced = False

            def walk(node):
                nonlocal replaced
                if isinstance(node, dict):
                    if node.get("type") == "table" and not replaced:
                        # replace fields in-place
                        node.clear()
                        node.update(new_table)
                        replaced = True
                        return
                    for k, v in node.items():
                        walk(v)
                elif isinstance(node, list):
                    for i, item in enumerate(node):
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "table"
                            and not replaced
                        ):
                            node[i] = new_table
                            replaced = True
                            return
                        else:
                            walk(item)

            # operate on a copy to avoid mutating original unexpectedly
            desc_copy = adf_desc
            walk(desc_copy)
            if not replaced:
                # try to append to top-level content if present
                if (
                    isinstance(desc_copy, dict)
                    and "content" in desc_copy
                    and isinstance(desc_copy["content"], list)
                ):
                    desc_copy["content"].append(new_table)
                    replaced = True
                else:
                    # fallback: create new doc containing original and table
                    desc_copy = {
                        "type": "doc",
                        "version": 1,
                        "content": [adf_desc, new_table],
                    }
                    replaced = True
            return desc_copy, replaced

        # Replace or append the table in the original description
        new_desc, did_replace = replace_or_append_first_table(desc, new_table_node)

        # If we modified the description, push update to Jira
        if did_replace:
            # Respect local testing toggle — set SKIP_JIRA_UPDATE=1 to avoid making network calls
            if os.getenv("SKIP_JIRA_UPDATE"):
                append_summary(
                    "(SKIP_JIRA_UPDATE set) Prepared new description but did not call Jira API."
                )
                # Prepare a stable ADF doc to show for debugging
                if isinstance(new_desc, dict) and new_desc.get("type") == "doc":
                    final_desc = new_desc
                else:
                    final_desc = {"type": "doc", "version": 1, "content": [new_desc]}
                # Add trimmed JSON payload to summary for debugging
                try:
                    preview = json.dumps(final_desc, ensure_ascii=False)
                    preview_short = (
                        preview if len(preview) < 2000 else preview[:1997] + "..."
                    )
                    append_summary("Prepared payload (truncated):")
                    append_summary(preview_short)
                except Exception:
                    pass
                write_output(
                    "error_message",
                    "SKIP_JIRA_UPDATE: new description prepared but not applied",
                )
            else:
                # perform Jira update
                try:
                    # Ensure we send a valid ADF doc object as the description
                    if isinstance(new_desc, dict) and new_desc.get("type") == "doc":
                        final_desc = new_desc
                    else:
                        final_desc = {
                            "type": "doc",
                            "version": 1,
                            "content": [new_desc],
                        }
                    url = f"{base}/rest/api/3/issue/{args.jira_key}"
                    payload = {"fields": {"description": final_desc}}
                    headers_req = {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    }
                    r = requests.put(
                        url, json=payload, auth=(email, token), headers=headers_req
                    )
                    if r.status_code >= 300:
                        die(
                            f"Failed to update Jira issue description: {r.status_code}: {r.text[:1000]}"
                        )
                    # success
                    write_output("error_message", "")
                    append_summary("Description updated in Jira")
                except Exception as e:
                    die(f"Exception while updating Jira description: {e}")

    # Build the final summary now so the "Full table" reflects post-upsert state
    summary_parts = [
        f"### Jira Issue: **{args.jira_key}**{(' — ' + issue_summary) if issue_summary else ''}",
        f"- Type is {args.issuetype}: **{is_correct_type}**",
        f"- Ticket status: **{current_status}**",
        f"- Status allows upsert: **{status_allows_upsert}**",
        f"- Has description: **{has_description}**",
        f"- Found table: **{has_table}**",
    ]

    # Add upsert permission field information if provided
    if args.upsert_permission_field_id:
        field_name = jira_get_field_metadata(
            base, email, token, args.upsert_permission_field_id
        )
        permission_field_value = fields.get(args.upsert_permission_field_id)
        if permission_field_value is not None:
            if isinstance(permission_field_value, dict):
                field_value = permission_field_value.get("value", "")
            else:
                field_value = str(permission_field_value)
            summary_parts.append(
                f"- Upsert permission field '{field_name}': **{field_value}**"
            )
        else:
            summary_parts.append(
                f"- Upsert permission field '{field_name}': **Not accessible**"
            )
    if has_table:
        summary_parts.append("\n**Full table (after upsert):**\n")
        summary_parts.append(full_tbl_md or "_(empty)_")
    if upsert_summary:
        summary_parts.extend(upsert_summary)

    # Append the summary and also print to stdout for logs
    append_summary("\n".join(summary_parts))
    print("\n".join(summary_parts))

    # Hard validations you care about (non-zero exit on failure)
    if not is_correct_type:
        die(f"Issue {args.jira_key} is not of type {args.issuetype}")
    # If an upsert was requested we already created/prepared the table and
    # updated (or prepared to update) the description. In that case avoid
    # failing on missing description/table so the upsert flow can succeed.
    if upsert_raw:
        return
    if not has_description:
        die(f"Issue {args.jira_key} has no description")
    if not has_table:
        die(f"Issue {args.jira_key} description has no ADF table")


if __name__ == "__main__":
    main()
