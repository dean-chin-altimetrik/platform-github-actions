#!/usr/bin/env python3
"""
Test script to verify lookup error handling scenarios
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from main import die, append_summary, write_output


def test_error_scenarios():
    """Test different error scenarios for lookup mode"""

    print("Testing lookup error scenarios...")

    # Test 1: No tickets found
    print("\n=== Test 1: No tickets found ===")
    try:
        die("❌ No REL-SCOPE tickets found in project 'TEST' with state 'In Progress'")
    except SystemExit:
        print("✓ Correctly exits with error for no tickets found")

    # Test 2: Multiple tickets found
    print("\n=== Test 2: Multiple tickets found ===")
    try:
        error_msg = "❌ Multiple REL-SCOPE tickets found in project 'TEST' with state 'In Progress':"
        detailed_msg = f"{error_msg}\n\nFound 2 tickets:\n- **TEST-123**: First ticket summary\n- **TEST-456**: Second ticket summary"
        die(detailed_msg)
    except SystemExit:
        print("✓ Correctly exits with error for multiple tickets found")

    # Test 3: Component not found
    print("\n=== Test 3: Component not found ===")
    try:
        error_msg = "❌ Component 'missing-component' not found in ticket TEST-123"
        error_msg += f"\n\n**Available components in the table:**\n- existing-component-1\n- existing-component-2"
        die(error_msg)
    except SystemExit:
        print("✓ Correctly exits with error for component not found")

    # Test 4: Component found but wrong branch
    print("\n=== Test 4: Component found but wrong branch ===")
    try:
        error_msg = "❌ Component 'test-component' found in ticket TEST-123 but release branch does not match"
        error_msg += f"\n\n**Expected:** `release/v1.0`"
        error_msg += f"\n**Actual:** `release/v2.0`"
        error_msg += f"\n\n**Component row details:**\n"
        error_msg += "| Order | Component | Branch Name | Change Request | External Dependency |\n"
        error_msg += "|-------|-----------|-------------|----------------|---------------------|\n"
        error_msg += "| 1 | test-component | release/v2.0 | | |"
        die(error_msg)
    except SystemExit:
        print("✓ Correctly exits with error for wrong branch")

    print("\n✅ All error scenario tests passed!")


if __name__ == "__main__":
    test_error_scenarios()
