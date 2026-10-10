"""Read-only Docker-inspect reproduction under an explicitly limited cgroup.

Card work-card-1b0e37ea-795e-4993-9399-6bf9ccbda83c. No container changes.
"""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--attempts',type=int,default=10)
    args=parser.parse_args()
    config=json.loads(Path('/opt/trading-lab-resource-monitor-v1/config.json').read_text())
    cgroup=Path('/sys/fs/cgroup')/Path('/proc/self/cgroup').read_text().strip().split('::')[1].lstrip('/')
    results=[]
    if not 1<=args.attempts<=100:raise ValueError('bounded_attempts_required')
    template='{"name":{{json .Name}},"state":{{json .State.Status}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}},"restarts":{{.RestartCount}}}'
    for attempt in range(args.attempts):
        result=subprocess.run(['docker','inspect','--format',template,*config['containers']],
                              capture_output=True,text=True,timeout=15)
        results.append(dict(attempt=attempt,exit_code=result.returncode,
            thread_failure=('pthread_create failed' in result.stderr or 'failed to create new OS thread' in result.stderr),
            lines=len(result.stdout.splitlines()),pids_events=(cgroup/'pids.events').read_text().strip()))
    Path(args.output).write_text(json.dumps(results,indent=2))
    print(json.dumps(dict(attempts=len(results),failures=sum(r['exit_code']!=0 for r in results),
                         pids_events=results[-1]['pids_events'])))


if __name__=='__main__':main()
