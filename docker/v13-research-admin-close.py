#!/usr/bin/env python3
"""Local root-authenticated research paper close; no network or predictions.
Work card: work-card-77c03de2-8219-4ee0-8d56-a8651e760613.
"""
import argparse,datetime,json,os,pathlib,socket,uuid
if os.geteuid()!=0:raise SystemExit('Amministratore locale root richiesto.')
p=argparse.ArgumentParser(description=__doc__);p.add_argument('symbol');p.add_argument('--quantity',type=float);args=p.parse_args()
base=pathlib.Path(__file__).resolve().parents[2]/'octobot-local'
h=json.loads((base/'v13-paper/research/execution/health-research.json').read_text());position=next(v for v in h['positions'] if v['symbol']==args.symbol)
now=datetime.datetime.now(datetime.timezone.utc)
request=dict(account='v13-paper-v2',symbol=args.symbol,position_id=position['position_id'],generation=position['generation'],quantity=args.quantity if args.quantity is not None else abs(position['quantity']),nonce=uuid.uuid4().hex,issued_at=now.isoformat(),expires_at=(now+datetime.timedelta(seconds=60)).isoformat())
with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
 s.settimeout(45);s.connect(str(base/'v13-research-admin/close.sock'));s.sendall(json.dumps(request,allow_nan=False).encode()+b'\n');response=b''
 while not response.endswith(b'\n'):
  part=s.recv(8192)
  if not part:raise SystemExit('Risposta incompleta: verificare ledger/nonce prima di ripetere.')
  response+=part
 print(response.decode().strip())
