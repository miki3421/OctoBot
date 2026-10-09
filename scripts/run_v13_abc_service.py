"""Explicit ABC controller entry point; requires reviewed configuration and pins."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root),str(root/'octobot/ai_strategy_lab')]
from v13_dynamic_service import main
if __name__=='__main__':raise SystemExit(main())
