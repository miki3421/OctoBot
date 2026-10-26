"""Real published V13 derivation on full M1 copy; no baseline/derive mocks."""
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_auto as auto
from octobot.ai_strategy_lab import v13_m1_paper as base
from octobot.ai_strategy_lab.v13_m1_paper_view import publish

E=Path('/evidence');F=E/('published-bundle-'+uuid.uuid4().hex[:8]);F.mkdir(mode=0o750);os.chown(F,0,30910)
for name,uid in [('state',30943),('projection',30943),('configuration',0)]:
    p=F/name;p.mkdir(mode=0o750);os.chown(p,uid,30910)
shutil.copyfile(E/'m1.sqlite',F/'state/account.sqlite');os.chown(F/'state/account.sqlite',30943,30910);(F/'state/account.sqlite').chmod(0o640)


def write(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n');os.chown(path,0,30910);path.chmod(0o440)


cfg=json.loads(Path('/release/configuration/config.json').read_text())
for name in ('protocol','successor-proposal','successor-authority','genesis-upgrade','automatic-authority'):
    shutil.copyfile(Path('/release/configuration')/(name+'.json'),F/'configuration'/(name+'.json'));os.chown(F/'configuration'/(name+'.json'),0,30910);(F/'configuration'/(name+'.json')).chmod(0o440)
cfg.update(db=str(F/'state/account.sqlite'),protocol=str(F/'configuration/protocol.json'),runtime_upgrade=str(F/'configuration/runtime-upgrade.json'),output=str(F/'projection/account.json'))
cfg['management']['projection']=str(F/'projection/management.json')
for section,field,name in [('successor','proposal','successor-proposal'),('successor','authority','successor-authority'),('successor','genesis_upgrade','genesis-upgrade'),('automatic_review','authority','automatic-authority')]:cfg[section][field]=str(F/'configuration'/(name+'.json'))
cfg['management']['transition_proposal']=str(F/'configuration/successor-proposal.json')
upgrade=json.loads(Path('/release/configuration/runtime-upgrade-template.json').read_text());upgrade.update(authorized_at=base.source.now().isoformat(),owner_reference='FULL COPY QUALIFICATION ONLY: published scientific bundle',backup_sha256=base.shared.sha(E/'m1.sqlite'));write(F/'configuration/runtime-upgrade.json',upgrade)
db=sqlite3.connect(F/'state/account.sqlite');before_orders=db.execute('SELECT COUNT(*) FROM orders').fetchone()[0];before_control=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0]);before_state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);before_policy=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='management_policy'").fetchone()[0]);db.close()
os.setgroups([30910]);os.setgid(30910);os.setuid(30943)
runner=auto.Runner(cfg)
now=base.source.now();runner.market_record(now)
assert len(runner.universe)==6,'fixture needs the production six-symbol execution scope'
control=runner.meta('control');runner.baseline(control,now)
assert control['baseline_day']==str(now.date()-dt.timedelta(days=1))
assert set(control['baseline_targets'])==set(runner.universe)
row=runner.db.execute('SELECT payload FROM inputs WHERE day=?',(control['baseline_day'],)).fetchone();item=json.loads(row[0]);assert len(item['prices'])==18 and len(item['targets'])==18
assert item['proposal_id']==json.loads(Path('/proposals/latest.json').read_text())['proposal_id']
# Exercise an admitted execution asset without rewriting the original bundle.
runner.universe.append('QNTUSDT');runner.baseline(control,base.source.now());assert control['baseline_targets']['QNTUSDT']==0.;runner.universe.remove('QNTUSDT')
# The detector is outside this correction. Baseline, source reader, derivation,
# accounting and funding are deliberately left unmocked.
with patch.object(base.causal,'read_window',return_value=None):runner.tick()
state=json.loads(runner.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);control=runner.meta('control')
assert control['baseline_error'] is None
assert runner.db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==before_orders
assert {s:v['quantity'] for s,v in state['positions'].items()}=={s:v['quantity'] for s,v in before_state['positions'].items()}
assert runner.managed_policy()['short_caps']==before_policy['short_caps']
assert runner.managed_policy()['quantity_ceilings']==before_policy['quantity_ceilings']
denied=runner.db.execute("SELECT status,payload FROM m1_slots WHERE kind='DAILY' AND slot='2026-10-26T00:15:00+00:00'").fetchone();assert denied['status']=='DENIED'
assert runner.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
publish(runner);runner.publish_management();runner.close()
runner=auto.Runner(cfg);runner.market_record(base.source.now());runner.baseline(runner.meta('control'),base.source.now());assert len(runner.universe)==6
result=dict(passed=True,real_published_derivation=True,baseline_mocked=False,scientific_universe=18,execution_universe=6,admitted_asset_projection_zero=True,
    history_retained=before_orders,no_retroactive_fill=True,missed_slot_preserved=True,positions_and_short_budget_preserved=True,restart_idempotent=True)
(F/'projection/result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));runner.close()
