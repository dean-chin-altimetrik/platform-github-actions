#!/usr/bin/env python3
import argparse, json, os, sys
import requests
from tabulate import tabulate

def die(msg, status=1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(status)

def jira_get_issue(base, email, token, key):
    url = f"{base}/rest/api/3/issue/{key}"
    params = {"fields": "issuetype,description"}
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
    ap.add_argument("--search-column", default="")
    ap.add_argument("--search-value", default="")
    args = ap.parse_args()

    base = os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")
    if not all([base, email, token]):
        die("Missing JIRA_BASE_URL, JIRA_EMAIL, or JIRA_API_TOKEN in env.")

    issue = jira_get_issue(base, email, token, args.jira_key)
    fields = issue.get("fields", {})
    issuetype = (fields.get("issuetype") or {}).get("name", "")
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
    if args.search_column and args.search_value and has_table:
        # case-insensitive column match
        try:
            idx = [h.lower().strip() for h in headers].index(args.search_column.lower().strip())
            matched_rows = [r for r in rows if args.search_value.lower() in (r[idx] or "").lower()]
        except ValueError:
            matched_rows = []  # column not found

    # Render tables (full + matched)
    full_tbl_md = ""
    if has_table:
        full_tbl_md = tabulate(rows, headers=headers, tablefmt="github")

    matched_tbl_md = ""
    if args.search_column and args.search_value and has_table:
        matched_tbl_md = tabulate(matched_rows, headers=headers, tablefmt="github")

    # Step Summary
    summary_parts = [
        f"### Jira Issue: **{args.jira_key}**",
        f"- Type is REL-SCOPE: **{is_rel_scope}**",
        f"- Has description: **{has_description}**",
        f"- Found table: **{has_table}**",
    ]
    if has_table:
        summary_parts.append("\n**Full table (first table in description):**\n")
        summary_parts.append(full_tbl_md or "_(empty)_")
    if matched_tbl_md:
        summary_parts.append("\n**Matched rows:**\n")
        summary_parts.append(matched_tbl_md or "_(no matches)_")
    append_summary("\n".join(summary_parts))

    # Outputs
    write_output("table_markdown", full_tbl_md)
    write_output("matched_rows_json", matched_rows)

    # Also print to stdout for logs
    print("\n".join(summary_parts))

    # Hard validations you care about (non-zero exit on failure)
    if not is_rel_scope:
        die(f"Issue {args.jira_key} is not of type REL-SCOPE")
    if not has_description:
        die(f"Issue {args.jira_key} has no description")
    if not has_table:
        die(f"Issue {args.jira_key} description has no ADF table")

if __name__ == "__main__":
    main()
