"""Offline-only adapter of the existing M1 single-writer runner.

No main/activation entrypoint. Constructor confines all writes to an explicitly
marked audit work copy. Production loading requires a separate future handoff.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3

from . import v13_m1_auto as automatic
from . import v13_m1_short_risk as risk

base = automatic.base


def guard(config):
    c=config['short_candidate'];root=Path(c['work_root']).resolve()
    if c['scope']!='OFFLINE_QUALIFICATION_ONLY' or 'audit-evidence' not in root.parts or 'octobot-local' in root.parts:
        raise ValueError('offline_work_copy_only')
    marker=root/'OFFLINE_ONLY.json'
    if marker.is_symlink() or marker.stat().st_mode & 0o222:
        raise ValueError('sealed_work_marker_required')
    value=json.loads(marker.read_text())
    protocol=json.loads(Path(c['protocol']).read_text());risk.validate(protocol)
    if (value['protocol_id']!=risk.PROTOCOL_ID or value['account']!=protocol['account']
            or value['scope']!='OFFLINE_COPY_NO_OPERATING_AUTHORITY'):
        raise ValueError('work_copy_identity')
    for path in (config['db'],config['output'],config['management']['projection']):
        raw=Path(path)
        if raw.is_symlink() or not raw.resolve().is_relative_to(root):
            raise ValueError('write_path_outside_work_copy')
    for name in ('original','seed'):
        path=Path(config[name])
        if path.is_symlink() or path.stat().st_mode & 0o222:
            raise ValueError('read_only_source_copy_required')
    return protocol,value


class Runner(automatic.Runner):
    def __init__(self,config):
        self.short_protocol,self.copy_identity=guard(config)
        self._short_history_cache=None
        super().__init__(config)
        if self.account!=self.short_protocol['account']:
            raise ValueError('candidate_account_changed')
        identity=self.meta('short_candidate_identity')
        expected=dict(protocol_id=risk.PROTOCOL_ID,account=self.account,
                      marker_source=self.copy_identity['source_sha256'],scope='OFFLINE_ONLY')
        if identity and identity!=expected:
            raise ValueError('candidate_reactivation_conflict')
        if not identity:
            control=self.meta('control')
            state=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            if control['phase']!='NORMAL' or control.get('pending') or any(p['quantity']<0 for p in state['positions'].values()):
                raise ValueError('candidate_requires_normal_no_open_legacy_short')
            with self.db:
                self.put('short_candidate_identity',expected)
                self.event('SHORT_CANDIDATE_PREPARED',expected)

    def pending_targets(self,state,control,record,kind,weights,target):
        weights,target=super().pending_targets(state,control,record,kind,weights,target)
        if kind!='M1_ENTRY':
            return weights,target
        try:
            row=self.db.execute('SELECT signal_at,payload FROM m1_episodes WHERE id=?',(control['episode'],)).fetchone()
            if not row:
                raise ValueError('episode_signal_missing')
            observed=json.loads(row['payload'])
            history=risk.model(observed['consumed_rows'],base.p.timestamp(row['signal_at']).timestamp())
            if base.causal.digest(observed['consumed_rows'])!=observed['input_hash']:
                raise ValueError('consumed_signal_identity')
            plan=risk.size(self.short_protocol,history,base.paper.totals(state,require_positive=False)['equity'],
                           self.managed_policy()['short_caps'],record['quotes'])
            # Parent admission/weekly permissions remain the upper bound.
            if any(s not in target or target[s]>=0 or q<target[s]-1e-10 for s,q in plan['quantities'].items()):
                raise ValueError('parent_short_permission_missing')
            target={s:(plan['quantities'].get(s,0.) if q<0 and state['positions'][s]['quantity']>=0 else q)
                    for s,q in target.items()}
            self.put('short_candidate_plan',plan)
            self.put('short_candidate_input_status',None)
            self.event('SHORT_RISK_PLAN',plan,self.managed_policy()['proposal_id'])
        except (ValueError,KeyError,TypeError,ZeroDivisionError) as error:
            # Same protective behavior as a parent M1 entry veto: do not
            # manufacture a smaller unqualified SHORT or restore a LONG.
            target={s:(0. if state['positions'][s]['quantity']>=0 else state['positions'][s]['quantity'])
                    for s in state['positions'] if s in record['quotes']}
            self.put('short_candidate_plan',None)
            self.put('short_candidate_input_status','NO_NEW_SHORT:'+str(error)[:100])
        return self.weights_from_quantities(state,target),target

    def execute_pending(self,state,control,record,now,debt):
        pending=copy.deepcopy(control.get('pending'))
        result=super().execute_pending(state,control,record,now,debt)
        if not pending or control.get('pending'):
            return result
        if pending['kind']=='M1_ENTRY' and control['phase']=='ACTIVE':
            plan=self.meta('short_candidate_plan')
            if plan and any(p['quantity']<0 for p in result['positions'].values()):
                fills=[json.loads(row[0]) for row in self.db.execute(
                    'SELECT payload FROM m1_fills WHERE json_extract(payload,\'$.decision_id\')=? ORDER BY symbol',
                    (pending['id'],))]
                saved=risk.episode(plan,state['positions'],result['positions'],fills,
                                   base.p.timestamp(record['observed_at_end']).timestamp(),control['episode'])
                self.put('short_candidate_episode',saved)
                self.event('SHORT_RISK_EPISODE_OPENED',saved)
        elif pending['kind']=='EXIT':
            saved=self.meta('short_candidate_episode')
            if saved and saved['episode_id']==control['episode'] and control['phase']=='REENTRY_PENDING':
                saved.update(closed_at=record['observed_at_end'],status='CLOSED',
                             exit_reason=saved['exit_reason'] or 'MAX_HOLD')
                self.put('short_candidate_episode',saved)
                self.event('SHORT_RISK_EPISODE_CLOSED',saved)
        return result

    def management_cycle(self,state,control,record,now,debt):
        state,record=super().management_cycle(state,control,record,now,debt)
        saved=self.meta('short_candidate_episode')
        if not saved or saved['episode_id']!=control.get('episode') or saved.get('status')=='CLOSED':
            return state,record
        if control['phase']=='EXIT_PENDING' and saved['exit_reason'] and not control.get('pending'):
            # A partial protective exit must retry promptly, not wait until
            # the original six-hour deadline after an early exit decision.
            self.intent(control,'EXIT',None,now,now)
        if control['phase']!='ACTIVE' or control.get('pending'):
            return state,record
        slot=int(now.timestamp())//300*300
        feature=None;feature_slot=None
        if slot>=saved['at']:
            feature_slot=slot
            try:
                if not self._short_history_cache or self._short_history_cache['slot']!=slot:
                    rows=base.causal.read_window(self.c['original'],slot,self.signal_universe())
                    self._short_history_cache=risk.model(rows,slot)
                feature=self._short_history_cache['feature']
            except (ValueError,KeyError,TypeError,OSError):
                feature=None
        try:
            if debt:
                raise ValueError('funding_debt')
            watched,reason=risk.watch(self.short_protocol,saved,state['positions'],record['quotes'],
                at=base.p.timestamp(record['observed_at_end']).timestamp(),market_id=record['record_hash'],
                feature_slot=feature_slot,feature=feature)
            self.put('short_candidate_episode',watched);self.put('short_candidate_input_status',None)
            if reason:
                control['phase']='EXIT_PENDING';self.intent(control,'EXIT',None,now,now)
                self.event('SHORT_RISK_EXIT_DECISION',dict(reason=reason,episode=watched))
        except (ValueError,KeyError,TypeError,ZeroDivisionError):
            self.put('short_candidate_input_status','WAITING_EXECUTABLE_SHORT_VALUATION_TIMEOUT_UNCHANGED')
        return state,record
