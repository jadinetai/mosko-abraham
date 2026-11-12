"""ABRAHAM 0.33c Phase 1 (D-ABR-026): reconcile the acceptance record. Read-only, except --out.

  python -I -B tools/g033c/reconcile_033c.py --out <folder>

Checks, against the digests the records themselves give (cited per item):
  identities  the production kernel and the launcher 0.33.1 equal their full recorded digests; the DIAGNOSTIC
              launchpad and early-fail builds equal TR-0042's build manifest;
  indexes     every evidence index from ABR-BOOT-001 to 0.33.1 has its recorded digest, and every row still matches.
              The only permitted differences are the shared append-only logs (DECISIONS.md, test-records/INDEX.md):
              for those the indexed digest must equal a line-boundary prefix of today's file;
  packages    every audit package equals its .sha256 sidecar and the digest prefix its record gives;
  trees       the 0.33 workspaces get a full snapshot (path, size, mtime, SHA-256) to compare at the end of 0.33c;
  records     D-ABR-001.. and TR-0001.. are contiguous, each listed record file exists, and no decision accepts 0.33.
Standard library only.
"""
import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

C = Path(__file__).resolve().parents[2]
HOME = C.parent
APPEND_ONLY = {"DECISIONS.md", "test-records/INDEX.md"}

IDENT = {  # name: (path, full digest, where the record gives it)
    "kernel 0.33.0-dev (production)": (HOME / "work-0.33/build/abraham-kernel-0.33.0-dev.elf",
                                       "6b95b9a27a8eedd68dd5023dbf99e73716aa1be88780ddde406099679e119a21", "TR-0042, 0.33_REVIEW.md"),
    "kernel 0.33.0-dev (work-0.33c copy)": (C / "build/abraham-kernel-0.33.0-dev.elf",
                                            "6b95b9a27a8eedd68dd5023dbf99e73716aa1be88780ddde406099679e119a21", "TR-0042"),
    "launcher 0.33.1": (HOME / "vmlauncher-0.33.1/Abraham-VM-Launcher.exe",
                        "c09f1cbfb49ca9c5c99a8702b4c1388a436bc0784219daabbf014bde0d4dde18", "TR-0046"),
    "launcher 0.33 (superseded, preserved)": (HOME / "vmlauncher-0.33/Abraham-VM-Launcher.exe",
                                              "64d90d76d2f596c8e5dad8bb6c5444478cd95abe791964ec6e4a9ae3dab51930", "TR-0044"),
    "kernel 0.32b (accepted foundation)": (HOME / "work-0.32b/build/abraham-kernel-0.32.1-dev.elf",
                                           "81d4b4ec86684f45a4e6ebb81cdf3e1532679d8c3711049a54b17ed486f64679", "D-ABR-023"),
}
INDEXES = [  # (index file, full recorded digest or None, record)
    ("frozen/ABR-BOOT-001-accepted/FREEZE_MANIFEST.sha256", "9085367e5036480cdb4904ae28e3e34469453d9a3ddf3e2088281d1ea16dd6a8", "TR-0014"),
    ("work-0.29/EVIDENCE_INDEX_0.29_SIGNOFF.sha256", "98d15717b35790435ef46fbb34aec5abbbbf25d0f7e151af0dde1b1184e3449f", "D-ABR-008"),
    ("work-0.31/EVIDENCE_INDEX_0.31a.sha256", None, "TR-0033"),
    ("work-0.31b/EVIDENCE_INDEX_0.31b.sha256", "81b565fb3b5d9a3bdc375236fec4ada65cd0db0631ae4c06ae047fbd8edafa71", "D-ABR-017"),
    ("work-0.32/EVIDENCE_INDEX_0.32.sha256", None, "TR-0037"),
    ("work-0.32b/EVIDENCE_INDEX_0.32b.sha256", "c69a91e0ce413afcbecd216dc910bbaeb1c5a0cd21313c2bf6cf07cc3682a81a", "D-ABR-023"),
    ("gate-0.32b/GATE_EVIDENCE_INDEX_0.32b.sha256", "195291e749ea7c261efaa853d4c5b94e6bc9df867fd81dac4b734645002a9a5b", "D-ABR-023"),
    ("work-0.33/EVIDENCE_INDEX_0.33.sha256", "60a1ff66fb8b9738d0aecef21a717dcd6f35f398d8cafbd69b480a411cabb839", "TR-0042"),
    ("vmlauncher-0.33/EVIDENCE_INDEX_VML_0.33.sha256", "50f2fc198c7a40d3aa027acac6a9ae31972ac05ab70d08d0ddce905fb1a2c382", "TR-0044"),
    ("vmlauncher-0.33.1/EVIDENCE_INDEX_VML_0.33.1.sha256", "f5926be56cb0acf93aa2ad01a303e1490523ca568fab1e04a9183baea6d30920", "TR-0046"),
]
PACKAGES = [  # (zip, recorded digest prefix, record)
    ("work-0.32b/evidence/review/ABRAHAM_0.32b_ECHO_AUDIT.zip", "7abf391a", "D-ABR-023"),
    ("gate-0.32b/review/ABRAHAM_0.32b_FINAL_AUDIT.zip", "59618e90", "D-ABR-023"),
    ("work-0.33/evidence/review/ABRAHAM_0.33_ECHO_AUDIT.zip", "cff95880", "TR-0042 INDEX row"),
    ("vmlauncher-0.33/evidence/review/ABRAHAM_0.33_VM_LAUNCHER_AUDIT.zip", "d7346e9d", "TR-0044 INDEX row"),
    ("vmlauncher-0.33.1/evidence/review/ABRAHAM_0.33.1_VM_LAUNCHER_AUDIT.zip", "288c5a4b", "TR-0046 INDEX row"),
]
TREES = ["work-0.33", "vmlauncher-0.33", "vmlauncher-0.33.1"]
# Differences an earlier record already reported, accepted only with the exact digest that record (and the later
# indexes) give: (index, file) -> (record, today's expected digest).
KNOWN = {("work-0.31/EVIDENCE_INDEX_0.31a.sha256", "work-0.31/docs/PATCH_NOTES_0.31a.md"):
         ("TR-0034: item 9 added after indexing; the indexed version is the one in Echo's 0.31a zip",
          "137e36f24582af13723bc1a36658bcd0704a42b63b5d5e0cb4bd39ca8637c14e")}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def resolve(index, rel):
    rel = rel.strip().lstrip("*").replace("\\", "/")
    for base in (HOME, index.parent):
        p = (base / rel).resolve()
        if p.is_file():
            return p
    return None


def prefix_match(p, digest):
    b = p.read_bytes()
    ends = [i + 1 for i, c in enumerate(b) if c == 10] + [len(b)]
    for e in ends:
        if hashlib.sha256(b[:e]).hexdigest() == digest:
            return e
    return None


def check_index(rel, recorded):
    idx = HOME / rel
    out = {"index": rel, "sha256": sha(idx), "recorded": recorded}
    out["digest_matches_record"] = recorded is None or out["sha256"] == recorded
    rows = [l for l in idx.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    bad, appended = [], []
    for l in rows:
        # Two columns (`sha  path`) or three (`sha  category  path`); R002 guessed categories by their characters and
        # took `signoff-index-0.29` for a path (a defect of this tool, recorded).
        parts = l.split()
        d, path = parts[0], " ".join(parts[2:]) if len(parts) >= 3 else parts[1]
        p = resolve(idx, path)
        if p is not None and sha(p) == d:
            continue
        key = p.relative_to(HOME).as_posix() if p is not None and HOME in p.parents else path
        known = KNOWN.get((rel, key))
        if p is not None and known and sha(p) == known[1]:
            appended.append({"file": key, "known_recorded_difference": known[0]})
            continue
        if p is not None and key in APPEND_ONLY:
            cut = prefix_match(p, d)
            appended.append({"file": key, "append_only": cut is not None, "indexed_bytes": cut, "now_bytes": p.stat().st_size})
            if cut is None:
                bad.append(path)
            continue
        bad.append(path)
    out.update({"rows": len(rows), "mismatched": bad[:20], "mismatched_count": len(bad), "append_only_logs": appended})
    out["holds"] = out["digest_matches_record"] and not bad
    return out


def snapshot(tree):
    root = HOME / tree
    snap = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = Path(dp) / f
            st = p.stat()
            snap[p.relative_to(root).as_posix()] = [st.st_size, st.st_mtime_ns, sha(p)]
    return snap


def records():
    dec = (HOME / "DECISIONS.md").read_text(encoding="utf-8")
    ids = [int(m) for m in re.findall(r"^\| D-ABR-(\d{3}) \|", dec, re.M)]
    accept = [l.split("|")[1].strip() + ": " + l.split("|")[3].strip()[:90]
              for l in dec.splitlines() if re.match(r"^\| D-ABR-\d{3} \|", l)
              and re.search(r'"(Accept|Sign off)[^"]*"', l.split("|")[3])]
    claims_033 = [l.split("|")[1].strip() for l in dec.splitlines() if re.search(r"0\.33 is ACCEPTED|ABRAHAM 0\.33 is ACCEPTED", l)]
    idx = (HOME / "test-records" / "INDEX.md").read_text(encoding="utf-8")
    trs = [int(m) for m in re.findall(r"^\| TR-(\d{4}) \|", idx, re.M)]
    missing = [f"TR-{n:04d}" for n in trs if f"[TR-{n:04d}.md]" in idx and not (HOME / "test-records" / f"TR-{n:04d}.md").is_file()]
    return {"decisions": f"D-ABR-{min(ids):03d}..D-ABR-{max(ids):03d}", "decisions_contiguous": ids == list(range(1, max(ids) + 1)),
            "acceptance_decisions": accept, "decision_accepting_0.33": claims_033,
            "test_records": f"TR-{min(trs):04d}..TR-{max(trs):04d}", "test_records_contiguous": trs == list(range(1, max(trs) + 1)),
            "listed_record_files_missing": missing}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    r = {"run_utc": datetime.now(timezone.utc).isoformat(), "identities": {}, "indexes": [], "packages": [], "trees": {}}
    for name, (p, d, src) in IDENT.items():
        got = sha(p) if p.is_file() else None
        r["identities"][name] = {"path": str(p), "sha256": got, "recorded": d, "source": src, "match": got == d}
    r["build_manifest_0.33"] = {k: v["sha256"] for k, v in json.loads(
        (HOME / "work-0.33/evidence/campaign-033/BUILD_MANIFEST.json").read_text())["kernels"].items() if k in ("default", "launchpad", "early")}
    r["build_manifest_matches_copy"] = all(sha(C / p) == d for p, d in (
        ("build/abraham-kernel-0.33.0-dev.elf", r["build_manifest_0.33"]["default"]),
        ("build/diag/abraham-kernel-diag-launchpad.elf", r["build_manifest_0.33"]["launchpad"]),
        ("build/diag/abraham-kernel-diag-early-fail.elf", r["build_manifest_0.33"]["early"])))
    for rel, rec, _src in INDEXES:
        r["indexes"].append(check_index(rel, rec))
    for rel, pre, src in PACKAGES:
        z = HOME / rel
        d = sha(z)
        side = (z.with_name(z.name + ".sha256").read_text().split() or [""])[0]
        r["packages"].append({"zip": rel, "sha256": d, "sidecar_matches": side == d, "record_prefix": pre,
                              "record_matches": d.startswith(pre), "source": src})
    for t in TREES:
        snap = snapshot(t)
        (out / f"{t}.snapshot.json").write_text(json.dumps(snap, sort_keys=True))
        r["trees"][t] = {"files": len(snap)}
    r["records"] = records()
    r["verdict"] = "RECONCILED" if (all(v["match"] for v in r["identities"].values()) and r["build_manifest_matches_copy"]
                                    and all(i["holds"] for i in r["indexes"])
                                    and all(p["sidecar_matches"] and p["record_matches"] for p in r["packages"])
                                    and r["records"]["decisions_contiguous"] and r["records"]["test_records_contiguous"]
                                    and not r["records"]["listed_record_files_missing"]
                                    and not r["records"]["decision_accepting_0.33"]) else "NOT RECONCILED"
    (out / "reconcile.json").write_text(json.dumps(r, indent=1) + "\n")
    sums = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    (out / "RUN_SHA256SUMS.json").write_text(json.dumps(sums, indent=1, sort_keys=True) + "\n")
    print(json.dumps({"verdict": r["verdict"],
                      "identities": {k: v["match"] for k, v in r["identities"].items()},
                      "indexes": {i["index"]: (i["rows"], i["holds"], i["mismatched_count"], [a["file"] for a in i["append_only_logs"]]) for i in r["indexes"]},
                      "packages": {p["zip"].split("/")[-1]: p["sidecar_matches"] and p["record_matches"] for p in r["packages"]},
                      "records": r["records"], "trees": r["trees"]}, indent=1))
    return 0 if r["verdict"] == "RECONCILED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
