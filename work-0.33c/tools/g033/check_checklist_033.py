"""ABRAHAM 0.33: every kernel digest in the operator checklist must be the one frozen in BUILD_MANIFEST.json.

  python -I -B tools/g033/check_checklist_033.py

Reads docs/0.33_OPERATOR_CHECKLIST.md. (The 0.32b checker with the 0.33 paths.) For every `--kernel <path> --expect-kernel-sha256 <digest>` pair, the digest
must equal the BUILD_MANIFEST entry for that path; `$k` must be the production kernel. Any other 64-hex value must
be a BUILD_MANIFEST digest, or the all-zero wrong-digest probe. Written after `campaign close`. Standard library only.
"""
import json
import re
import sys
from pathlib import Path

W = Path(__file__).resolve().parents[2]
DOC = W / "docs" / "0.33_OPERATOR_CHECKLIST.md"


def norm(p):
    p = p.replace("\\", "/")
    for tree in ("work-0.31b", "work-0.32b", "work-0.32"):
        p = p.replace(f"../{tree}/", f"C:/Users/XxUnd/OneDrive/Documents/Abraham/{tree}/")
    return p.lower()


def main():
    text = DOC.read_text(encoding="utf-8")
    kernels = json.loads((W / "evidence" / "campaign-033" / "BUILD_MANIFEST.json").read_text())["kernels"]
    by_path = {norm(v["path"]): v["sha256"] for v in kernels.values()}
    known = set(by_path.values())
    k = re.search(r'\$k\s+=\s+"([0-9a-f]{64})"', text)
    pairs = re.findall(r"--kernel (\S+) --expect-kernel-sha256 (\$k|[0-9a-f]{64})", text)
    results = []
    for path, d in pairs:
        want = by_path.get(norm(path))
        got = k.group(1) if d == "$k" else d
        results.append({"kernel": path, "digest": got, "manifest": want, "ok": want == got})
    others = sorted(set(re.findall(r"\b[0-9a-f]{64}\b", text)) - {r["digest"] for r in results})
    unknown = [d for d in others if d not in known and d != "0" * 64]
    ok = bool(k) and k.group(1) == kernels["default"]["sha256"] and results and all(r["ok"] for r in results) and not unknown
    report = {"checklist": str(DOC), "default_kernel_ok": bool(k) and k.group(1) == kernels["default"]["sha256"],
              "pairs": results, "other_digests": others, "unknown_digests": unknown, "verdict": "PASS" if ok else "FAIL"}
    print(json.dumps(report, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
