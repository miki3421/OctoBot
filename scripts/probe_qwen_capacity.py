"""Bounded synthetic capacity probe, outside all scientific forward records.

Card work-card-be726a89-5841-4655-86c8-07d5ab71eb86. Existing local model only.
No downloads, real market data, journal writes, slot replay or runtime tuning.
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import urllib.request

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('shadow_contract', root / 'octobot/ai_strategy_lab/qwen_btc_shadow_forward_v2.py')
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)
BASE = 'http://127.0.0.1:8090'


def local_get(path):
    with urllib.request.urlopen(BASE + path, timeout=5) as reply:
        return json.load(reply)


def sample(pid):
    stat = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()
    return dict(at=time.monotonic(), cpu_ticks=int(stat[11])+int(stat[12]),
        rss_bytes=int(stat[21])*os.sysconf('SC_PAGE_SIZE'),
        memory_pressure=Path('/proc/pressure/memory').read_text().strip(),
        cpu_pressure=Path('/proc/pressure/cpu').read_text().strip())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    destination = Path(args.output)
    destination.mkdir()
    pid = int(subprocess.check_output(['systemctl','show','llama-moe.service','-p','MainPID','--value'],text=True))
    system = ('PROVA TECNICA CON DATI SINTETICI, fuori da ogni esperimento forward. '
              'Le cifre sono inventate e non descrivono il mercato. Nessun ordine. ' + contract.SYSTEM)
    plan = dict(scope='SYNTHETIC_CAPACITY_ONLY', cases=[35,35,60],
        input='121 artificial daily closes; disjoint fictitious identifiers',
        generation='same sampling and schema as frozen contract; no changes to that contract',
        registered_at=dt.datetime.now(dt.timezone.utc).isoformat())
    (destination/'plan.json').write_text(json.dumps(plan,indent=2))
    results=[]
    for case, timeout in enumerate(plan['cases']):
        slots=local_get('/slots?fail_on_no_slot=1')
        if not slots or any(s.get('is_processing') is not False for s in slots):
            print('STOP: shared model busy'); break
        bars=[[1577836800000+i*86400000,format(70000+(i*137+case*29)%10000,'.1f')] for i in range(121)]
        source=dict(scope='SYNTHETIC_CAPACITY_ONLY', experiment_id='synthetic-runtime-probe',
            lineage='a'*64,symbol='SYNTHETIC_BTC',slot_utc='2020-05-01T00:10:00+00:00',
            input_cutoff_utc='2020-05-01T00:10:00+00:00',causal_bars=bars,
            causal_input_sha256='b'*64,observation_id=('c' if case==0 else 'd')*64)
        body=dict(model='moe-private',**contract.SAMPLING,
            response_format={'type':'json_schema','schema':contract.SCHEMA},
            messages=[dict(role='system',content=system),dict(role='user',content=contract.canonical(source).decode())])
        request=destination/(str(case)+'-synthetic-request.json')
        request.write_bytes(contract.canonical(body))
        samples=[];stop=threading.Event()
        def observe():
            while not stop.is_set():
                samples.append(sample(pid));stop.wait(1)
        thread=threading.Thread(target=observe);thread.start()
        started=time.monotonic()
        try:
            reply=subprocess.run(['curl','--disable','--silent','--show-error','--fail','--noproxy','*',
                '--proto','=http','--max-time',str(timeout),'--max-filesize','131072',
                '-H','Content-Type: application/json','--data-binary','@'+str(request),BASE+'/v1/chat/completions'],
                capture_output=True,timeout=timeout+3)
        finally:
            stop.set();thread.join()
        elapsed=time.monotonic()-started
        result=dict(case=case,timeout_seconds=timeout,elapsed_seconds=elapsed,curl_exit=reply.returncode,
            samples=samples,synthetic=True,forward_record_written=False)
        if not reply.returncode:
            value=json.loads(reply.stdout);choice=value['choices'][0]
            contract.output(choice['message']['content'])
            result.update(schema_valid=True,complete=choice.get('finish_reason')=='stop' and not choice['message'].get('reasoning_content'),
                usage=value.get('usage'),timings=value.get('timings'))
        if len(samples)>1:
            wall=samples[-1]['at']-samples[0]['at']
            result['mean_model_cpu_cores']=(samples[-1]['cpu_ticks']-samples[0]['cpu_ticks'])/os.sysconf('SC_CLK_TCK')/wall
        results.append(result)
        (destination/'results.json').write_text(json.dumps(dict(scope='SYNTHETIC_CAPACITY_ONLY',results=results),indent=2))
        print(json.dumps({k:v for k,v in result.items() if k not in ['samples','usage','timings']}),flush=True)
        time.sleep(1)


if __name__ == '__main__':
    main()
