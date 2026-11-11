"""Full verification = `tools/verify.py --all`. Kept as its own name so that the command in
CLAUDE.md never changes; the plan itself lives only in tools/verify.py."""
import subprocess
import sys
from pathlib import Path

sys.exit(subprocess.call([sys.executable, str(Path(__file__).with_name("verify.py")), "--all"]))
