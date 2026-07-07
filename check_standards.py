"""
check_standards.py
------------------
DevOps pre-flight linter for AP invoice extraction code.
Cross-references Python source against UBL 2.1 / PEPPOL BIS Billing 3.0 JSON schemas.

Usage:
    python check_standards.py \
        --source app/services/llm_extractor.py \
        --standard standards/ubl_21_invoice.json

    python check_standards.py \
        --source app/services/llm_extractor.py \
        --standard standards/peppol_bis_billing_3.json
"""

import ast
import json
import sys
import argparse
import textwrap
from pathlib import Path
from typing import Optional


# ── Data model ────────────────────────────────────────────────────────────────

class LintResult:
    def __init__(self, status, line, python_field, ubl_element, message):
        self.status = status
        self.line = line
        self.python_field = python_field
        self.ubl_element = ubl_element
        self.message = message


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_schema(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"[ERROR] Schema not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Schema malformed: {e}", file=sys.stderr)
        sys.exit(2)


def load_source(path: Path):
    try:
        source = path.read_text(encoding="utf-8")
        return source, ast.parse(source, filename=str(path))
    except FileNotFoundError:
        print(f"[ERROR] Source not found: {path}", file=sys.stderr)
        sys.exit(2)
    except SyntaxError as e:
        print(f"[ERROR] Source has syntax errors: {e}", file=sys.stderr)
        sys.exit(2)


# ── AST helpers ───────────────────────────────────────────────────────────────

def find_conversion_calls(tree: ast.Module, conversion_fns: list) -> list:
    calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in conversion_fns:
            fn = node.func.id
        elif isinstance(node.func, ast.Attribute) and node.func.attr in conversion_fns:
            fn = node.func.attr
        else:
            continue
        if not node.args:
            continue
        arg = node.args[0]
        calls.append({"line": node.lineno, "func_name": fn,
                       "arg_node": arg, "arg_repr": ast.unparse(arg)})
    return calls


def find_guard_coverage(source_lines: list, call_line: int) -> bool:
    window = "\n".join(source_lines[max(0, call_line - 15): call_line - 1])
    patterns = ["is None", "is not None", "if not ", "if raw", "if val",
                "if cleaned", "try:", "_NULL_TOKENS", "forbidden",
                ".lower() in", "== \"\"", "== ''", "== \"\""]
    return any(p in window for p in patterns)


def map_arg_to_field(arg_repr: str, field_defs: list) -> Optional[dict]:
    arg_lower = arg_repr.lower().replace('"', "'")
    for f in field_defs:
        candidates = [
            f["python_field"].lower(),
            f["python_field"].lower().split(".")[-1],
            f["ubl_element"].lower(),
        ]
        if any(c in arg_lower for c in candidates):
            return f
    return None


# ── Checks ────────────────────────────────────────────────────────────────────

def check_required_fields(source: str, field_defs: list) -> list:
    results = []
    for f in [x for x in field_defs if x.get("required")]:
        leaf = f["python_field"].split(".")[-1]
        present = leaf in source or f["python_field"] in source
        results.append(LintResult(
            status="PASS" if present else "FAIL",
            line=0,
            python_field=f["python_field"],
            ubl_element=f["ubl_element"],
            message=(
                f"Required field '{f['python_field']}' (UBL '{f['ubl_element']}') "
                + ("referenced in source." if present
                   else "NOT found in source — UBL 2.1 mandates this field.")
            )
        ))
    return results


def check_forbidden_tokens(tree: ast.Module, conversion_fns: list,
                            forbidden_tokens: list) -> list:
    results = []
    for call in find_conversion_calls(tree, conversion_fns):
        if isinstance(call["arg_node"], ast.Constant):
            val = str(call["arg_node"].value)
            if val in forbidden_tokens:
                results.append(LintResult(
                    status="FAIL",
                    line=call["line"],
                    python_field="(literal)",
                    ubl_element="(literal)",
                    message=(
                        f"Forbidden token '{val}' passed directly to "
                        f"{call['func_name']}() — must be intercepted before conversion."
                    )
                ))
    return results


def check_guard_coverage(tree: ast.Module, source_lines: list,
                          field_defs: list, conversion_fns: list) -> list:
    guarded = [f for f in field_defs if f.get("guard_required")]
    results = []
    for call in find_conversion_calls(tree, conversion_fns):
        matched = map_arg_to_field(call["arg_repr"], guarded)
        if matched is None:
            results.append(LintResult(
                status="WARN",
                line=call["line"],
                python_field="(unmapped)",
                ubl_element="(unmapped)",
                message=(
                    f"{call['func_name']}('{call['arg_repr']}') — "
                    f"argument not mapped to a known UBL field. Verify guard manually."
                )
            ))
            continue
        has_guard = find_guard_coverage(source_lines, call["line"])
        results.append(LintResult(
            status="PASS" if has_guard else "FAIL",
            line=call["line"],
            python_field=matched["python_field"],
            ubl_element=matched["ubl_element"],
            message=(
                f"Field '{matched['python_field']}' → UBL '{matched['ubl_element']}'. "
                + ("Guard detected." if has_guard
                   else f"Missing null/string guard before {call['func_name']}().")
            )
        ))
    return results


def check_peppol_rules(source: str, schema: dict) -> list:
    results = []
    rules = schema.get("business_rules", [])
    for rule in rules:
        field = rule.get("field", "")
        leaf = field.split(".")[-1] if field and field != "all_fields" else None
        if leaf and leaf not in ("all_fields", "profile_id", "buyer_endpoint",
                                  "seller_endpoint", "buyer_reference",
                                  "customization_id", "invoice_type_code"):
            present = leaf in source or field in source
            results.append(LintResult(
                status="PASS" if present else "WARN",
                line=0,
                python_field=field,
                ubl_element=rule.get("ubl_element", ""),
                message=(
                    f"[{rule['rule_id']}] {rule['message'][:90]} "
                    + ("— field referenced in source." if present
                       else "— field NOT found in source.")
                )
            ))
    return results


# ── Report ────────────────────────────────────────────────────────────────────

ICONS = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}


def render_report(source_path: Path, schema: dict, results: list) -> int:
    passes = [r for r in results if r.status == "PASS"]
    fails  = [r for r in results if r.status == "FAIL"]
    warns  = [r for r in results if r.status == "WARN"]

    standard = schema.get("standard", "Unknown Standard")
    ref      = schema.get("oasis_reference") or schema.get("peppol_reference", "")
    src      = schema.get("source", "")

    print()
    print("━" * 72)
    print(f"  AP Invoice Standards Linter")
    print(f"  Standard : {standard}")
    print(f"  Reference: {ref}")
    print(f"  Source   : {src}")
    print(f"  File     : {source_path}")
    print("━" * 72)
    print()

    for r in sorted(results, key=lambda x: (x.line, x.status)):
        icon = ICONS.get(r.status, "?")
        loc  = f"line {r.line:>4}" if r.line > 0 else "       —"
        print(f"  [{r.status}] {loc}: {icon}  {r.message}")

    print()
    print("━" * 72)
    print(f"  TOTAL {len(results)} checks │ "
          f"✅ {len(passes)} passed │ "
          f"❌ {len(fails)} failed │ "
          f"⚠️  {len(warns)} warnings")
    print("━" * 72)
    print()

    if fails:
        print("  ❌  Linter FAILED — resolve items above before deploying.\n")
        return 1
    print("  ✅  All checks passed. Code is compliant with the standard.\n")
    return 0


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AP Invoice DevOps Standards Linter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python check_standards.py \\
                  --source app/services/llm_extractor.py \\
                  --standard standards/ubl_21_invoice.json

              python check_standards.py \\
                  --source app/services/llm_extractor.py \\
                  --standard standards/peppol_bis_billing_3.json
        """),
    )
    parser.add_argument("--source",   required=True)
    parser.add_argument("--standard", required=True)
    args = parser.parse_args()

    schema, (source, tree) = load_schema(Path(args.standard)), load_source(Path(args.source))
    source_lines    = source.splitlines()
    field_defs      = schema.get("fields", schema.get("business_rules", []))
    forbidden       = schema.get("monetary_forbidden_tokens", [])
    conversion_fns  = schema.get("conversion_functions", [])

    results = []
    if "fields" in schema:
        results += check_required_fields(source, field_defs)
        results += check_forbidden_tokens(tree, conversion_fns, forbidden)
        results += check_guard_coverage(tree, source_lines, field_defs, conversion_fns)
    else:
        results += check_peppol_rules(source, schema)
        results += check_forbidden_tokens(tree, conversion_fns, forbidden)

    sys.exit(render_report(Path(args.source), schema, results))


if __name__ == "__main__":
    main()
