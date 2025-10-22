#!/usr/bin/env python3
import argparse, json, os, sys
import requests
from tabulate import tabulate

def die(msg, status=1):
    # Surface the error in three places:
    # 1) stderr (for logs),
    # 2) GITHUB_OUTPUT as `error_message` so workflows can read it as an output,
    # 3) step summary for quick visibility in the job UI.
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

def jira_get_issue(base, email, token, key):
    url = f"{base}/rest/api/3/issue/{key}"
    # Also request `summary` so we can include the issue title in the check summary
    params = {"fields": "issuetype,description,summary"}
    r = requests.get(url, params=params, auth=(email, token), headers={"Accept":"application/json"})
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
        is_header_row = all(c.get("type") == "tableHeader" for c in cells) and len(cells) > 0
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
    headers = (headers + [""] * (width - len(headers))) if headers else [f"Col{i+1}" for i in range(width)]
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jira-key", required=True)
    # New individual parameters (preferred).
    ap.add_argument("--component", default="", help="Component name to add/update")
    ap.add_argument("--branch-name", default="", help="Branch name for the component")
    args = ap.parse_args()

    base = os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_EMAIL") or "dean.chin@altimetrik.com"
    token = os.getenv("JIRA_API_TOKEN")
    # JIRA_EMAIL is optional and defaults to dean.chin@altimetrik.com
    missing = [
        name for name, val in (
            ("JIRA_BASE_URL", base),
            ("JIRA_API_TOKEN", token),
        ) if not val
    ]
    if missing:
        die(
            "Missing JIRA credentials in environment: " + ", ".join(missing) +
            ".\nProvide these as repository or organization secrets and pass them to the workflow (example in README)."
        )

    issue = jira_get_issue(base, email, token, args.jira_key)
    fields = issue.get("fields", {})
    issuetype = (fields.get("issuetype") or {}).get("name", "")
    issue_summary = (fields.get("summary") or "").strip()
    is_rel_scope = (issuetype == "REL-SCOPE")
    write_output("is_rel_scope", str(is_rel_scope).lower())

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

    matched_tbl_md = ""

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
        expected_headers = ["Order", "Component", "Branch Name", "Change Request", "External Dependency"]

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
                "Table headers do not match expected schema. Expected headers: " +
                ", ".join(expected_headers)
            )
            write_output("error_message", msg)
            append_summary(f"**ERROR:** {msg}")
            die(msg)

        # Parse upsert values: Component, Branch Name, Change Request, External Dependency
        parts = [p.strip() for p in upsert_raw.split(",")]
        if len(parts) < 1:
            die("Component value is required (provide --component and --branch-name inputs)")

        comp = parts[0]
        branch = parts[1] if len(parts) > 1 else ""
        change_req = parts[2] if len(parts) > 2 else ""
        ext_dep = parts[3] if len(parts) > 3 else ""

        # Case-insensitive search for Component in existing rows (Component is column index 1)
        comp_idx = 1
        found = False
        old_row = None
        for r in rows:
            if len(r) > comp_idx and (r[comp_idx] or "").strip().lower() == comp.strip().lower():
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
                max_order = max((int(r[0]) for r in rows if r and r[0] != ""), default=-1)
            except Exception:
                max_order = len(rows) - 1
            new_order = max_order + 1 if max_order >= 0 else 0
            new_row = [str(new_order), comp, branch, change_req, ext_dep]
            rows.append(new_row)

        # Prepare human-friendly upsert report and append to upsert_summary
        upsert_summary.append("\n**Upsert result:**\n")
        if old_row is not None:
            # Updated existing row: show before/after
            upsert_summary.append(f"- Updated Component **{comp}** (Order {old_row[0]}):\n")
            # render small markdown table showing before and after
            before_tbl = tabulate([old_row], headers=headers, tablefmt="github")
            after_row = None
            # find the updated row (match by order)
            for rr in rows:
                if rr and rr[0] == old_row[0]:
                    after_row = rr
                    break
            after_tbl = tabulate([after_row], headers=headers, tablefmt="github") if after_row else ""
            upsert_summary.append("**Before:**\n")
            upsert_summary.append(before_tbl)
            upsert_summary.append("**After:**\n")
            upsert_summary.append(after_tbl)
            # write outputs for update
            write_output("upsert_result", "updated")
            write_output("upserted_row_json", after_row)
        else:
            # Added new row: show the inserted row
            upsert_summary.append(f"- Added Component **{comp}** (Order {new_row[0]}):\n")
            upsert_summary.append(tabulate([new_row], headers=headers, tablefmt="github"))
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
            header_row = {"type": "tableRow", "content": [make_table_header_cell(h) for h in headers_list]}
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
                        if isinstance(item, dict) and item.get("type") == "table" and not replaced:
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
                if isinstance(desc_copy, dict) and "content" in desc_copy and isinstance(desc_copy["content"], list):
                    desc_copy["content"].append(new_table)
                    replaced = True
                else:
                    # fallback: create new doc containing original and table
                    desc_copy = {"type": "doc", "version": 1, "content": [adf_desc, new_table]}
                    replaced = True
            return desc_copy, replaced

        # Replace or append the table in the original description
        new_desc, did_replace = replace_or_append_first_table(desc, new_table_node)

        # If we modified the description, push update to Jira
        if did_replace:
            # Respect local testing toggle — set SKIP_JIRA_UPDATE=1 to avoid making network calls
            if os.getenv("SKIP_JIRA_UPDATE"):
                append_summary("(SKIP_JIRA_UPDATE set) Prepared new description but did not call Jira API.")
                # Prepare a stable ADF doc to show for debugging
                if isinstance(new_desc, dict) and new_desc.get("type") == "doc":
                    final_desc = new_desc
                else:
                    final_desc = {"type": "doc", "version": 1, "content": [new_desc]}
                # Add trimmed JSON payload to summary for debugging
                try:
                    preview = json.dumps(final_desc, ensure_ascii=False)
                    preview_short = preview if len(preview) < 2000 else preview[:1997] + "..."
                    append_summary("Prepared payload (truncated):")
                    append_summary(preview_short)
                except Exception:
                    pass
                write_output("error_message", "SKIP_JIRA_UPDATE: new description prepared but not applied")
            else:
                # perform Jira update
                try:
                    # Ensure we send a valid ADF doc object as the description
                    if isinstance(new_desc, dict) and new_desc.get("type") == "doc":
                        final_desc = new_desc
                    else:
                        final_desc = {"type": "doc", "version": 1, "content": [new_desc]}
                    url = f"{base}/rest/api/3/issue/{args.jira_key}"
                    payload = {"fields": {"description": final_desc}}
                    headers_req = {"Accept": "application/json", "Content-Type": "application/json"}
                    r = requests.put(url, json=payload, auth=(email, token), headers=headers_req)
                    if r.status_code >= 300:
                        die(f"Failed to update Jira issue description: {r.status_code}: {r.text[:1000]}")
                    # success
                    write_output("error_message", "")
                    append_summary("Description updated in Jira")
                except Exception as e:
                    die(f"Exception while updating Jira description: {e}")

    # Build the final summary now so the "Full table" reflects post-upsert state
    summary_parts = [
        f"### Jira Issue: **{args.jira_key}**{(' — ' + issue_summary) if issue_summary else ''}",
        f"- Type is REL-SCOPE: **{is_rel_scope}**",
        f"- Has description: **{has_description}**",
        f"- Found table: **{has_table}**",
    ]
    if has_table:
        summary_parts.append("\n**Full table (after upsert):**\n")
        summary_parts.append(full_tbl_md or "_(empty)_")
    if upsert_summary:
        summary_parts.extend(upsert_summary)

    # Append the summary and also print to stdout for logs
    append_summary("\n".join(summary_parts))
    print("\n".join(summary_parts))

    # Hard validations you care about (non-zero exit on failure)
    if not is_rel_scope:
        die(f"Issue {args.jira_key} is not of type REL-SCOPE")
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
