"""Development only: run every campaign entry into a scratch folder, to find defects in the campaign tool itself
before the counted run (the 0.33 lesson: dry-run every judge mode on real output first). Its results are never
counted; TR-0044 lists it as a development run.

  python -I -B tools/dry_run_campaign.py <scratch folder>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import campaign_vml as c  # noqa: E402

scratch = Path(sys.argv[1]).resolve()
c.OUT = scratch / "campaign-vml"
c.RUNS = c.OUT / "runs"
c.MENU_RUNS = c.OUT / "menu-runs"
c.P = "VML-0.33.2-DRY-"
sys.exit(c.main())
