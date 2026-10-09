"""Read-only candidate preparation report. Never installs, downloads or activates."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'octobot/ai_strategy_lab'))
from v13_release_preflight import assess,configurations

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True);p.add_argument('--bundle',required=True);p.add_argument('--repo',required=True)
    a=p.parse_args();plan=json.loads(Path(a.plan).read_text());manifest=json.loads(Path(a.bundle).read_text())
    result=assess(plan,manifest,a.repo);result['candidate_configurations']=configurations(plan)
    print(json.dumps(result,indent=2));return 0 if result['technical_checks_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
