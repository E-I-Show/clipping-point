import sys
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "cp_proto"
sys.path.insert(0, str(APP))
