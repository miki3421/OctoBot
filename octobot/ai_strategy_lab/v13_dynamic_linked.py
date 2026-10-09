"""Atomic synthetic runner-to-cash-ledger integration. No real-data activation."""
import datetime as dt
import math
try:
    from . import v13_dynamic_cash as cash
    from . import v13_dynamic_runner as runner
except ImportError:
    import v13_dynamic_cash as cash
    import v13_dynamic_runner as runner

SCOPE='SYNTHETIC_LINKED_ABC_V2'


class LinkedStore(cash.funding.OfflineStore):
    store_scope=SCOPE

    def __init__(self,path,*,create=False):
        super().__init__(path,create=create)
        try:
            if create:
                self.db.execute('CREATE TABLE consumed_intents(intent_id TEXT PRIMARY KEY, batch_id TEXT UNIQUE NOT NULL, decision_hash TEXT NOT NULL)')
            # Do not silently upgrade old files or recreate missing state.
            if [r[1] for r in self.db.execute('PRAGMA table_info(consumed_intents)')] != ['intent_id','batch_id','decision_hash']:
                raise ValueError('consumption_schema_missing')
        except BaseException:
            self.close();raise

    def reduce(self, previous, request):
        if previous and (previous.get('scope')!=SCOPE or runner.selector.digest(
                {k:v for k,v in previous.items() if k!='state_hash'})!=previous.get('state_hash')):
            raise ValueError('invalid_linked_state')
        source=request['runner']
        if source['id']!=request['id']:raise ValueError('linked_id_mismatch')
        state=previous['runner'] if previous else runner.accounting.initial_state()
        tick=runner.prepare(state,source)
        decision=tick.get('selection')
        if decision is not None:
            ident=decision['decision_id']
            if self.db.execute('SELECT 1 FROM consumed_intents WHERE intent_id=?',(ident,)).fetchone():
                raise ValueError('intent_already_consumed')
        updated,trades=runner.accounting.advance(state,tick)
        events=[]
        for e in tick['funding']['events']+tick.get('delayed_funding',[]):
            # Explicit fixture provenance, never presented as an observed book.
            events.append(dict(e,status='SYNTHETIC_TEST_MARK',mark_source_hash=runner.selector.digest(e),
                               mark_observed_at=(runner.selector.timestamp(e['at'])-dt.timedelta(microseconds=1)).isoformat()))
        imported=[dict(scope='SIMULATED_FILL_IMPORT_ONLY',id=runner.selector.digest([request['id'],i]),
                       at=tick['at'],**{k:t[k] for k in ('arm','symbol','quantity','price','fee')})
                  for i,t in enumerate(trades)]
        ledger=cash.advance(previous['cash'] if previous else None,dict(scope=cash.SCOPE,
                            start=source['start'],as_of=tick['at'],fills=imported,
                            estimate=dict(scope='SYNTHETIC_FUNDING_ESTIMATE_ONLY',events=events)))
        for arm in runner.accounting.ARMS:
            a,b=updated['arms'][arm],ledger['arms'][arm]
            for field in ('cash','fees','funding'):
                if not math.isclose(a[field],b[field],rel_tol=1e-12,abs_tol=1e-8):
                    raise ValueError('cash_accounting_divergence')
            for symbol in set(a['positions'])|set(b['positions']):
                if not math.isclose(a['positions'].get(symbol,0.),b['positions'].get(symbol,0.),rel_tol=1e-12,abs_tol=1e-10):
                    raise ValueError('position_accounting_divergence')
        result=dict(scope=SCOPE,runner=updated,cash=ledger,trades=trades,execution_ready=False,performance_evidence=False)
        if decision is not None:
            # Same outer transaction as all three balances and the batch insert.
            # A valid zero-fill decision is also consumed; no later retries on
            # a different book under a new batch ID.
            self.db.execute('INSERT INTO consumed_intents VALUES (?,?,?)',
                            (ident,request['id'],runner.selector.digest(decision)))
        result['state_hash']=runner.selector.digest(result)
        return result
