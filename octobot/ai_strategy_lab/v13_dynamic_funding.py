"""Pure offline funding reconciliation, not an operational ledger.

Accepts estimates from the verified-receipt adapter and explicitly supplied
post-fill position history. Missing prices remain null. Coverage is never
certified here, even when all observed events have a computable amount.
"""
import copy
try:
    from . import v13_dynamic_comparison as accounting
    from . import v13_dynamic_universe as selector
except ImportError:
    import v13_dynamic_comparison as accounting
    import v13_dynamic_universe as selector

SCOPE = 'OFFLINE_FUNDING_RECONCILIATION_V1'


class OfflineStore:
    """Explicit offline archive: one transaction for history, all arms and deltas.

    Not a cash ledger or execution authorization. No default path, migration,
    automatic creation on restart, or fallback after storage failure.
    """
    store_scope = SCOPE

    def reduce(self, previous, request):
        return reconcile(previous,request['estimate'],request['history'],
                         start=request['start'],as_of=request['as_of'])

    def __init__(self, path, *, create=False):
        import sqlite3
        from pathlib import Path
        p = Path(path).absolute()
        if p.is_symlink(): raise ValueError('symlink_store')
        if create:
            with p.open('xb'): pass
        elif not p.is_file():
            raise ValueError('offline_store_missing')
        self.db = sqlite3.connect(p.as_uri()+'?mode=rw',uri=True,isolation_level=None)
        try:
            self.db.execute('PRAGMA trusted_schema=OFF')
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                self.db.execute('BEGIN IMMEDIATE')
                self.db.execute('CREATE TABLE marker(scope TEXT NOT NULL)')
                self.db.execute('INSERT INTO marker VALUES (?)',(self.store_scope,))
                self.db.execute('CREATE TABLE batches(id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,state TEXT NOT NULL)')
                self.db.execute('COMMIT')
            if self.db.execute('SELECT scope FROM marker').fetchall() != [(self.store_scope,)]:
                raise ValueError('not_offline_funding_store')
            if self.db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                raise ValueError('offline_store_integrity')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def commit(self, request):
        import json
        if request.get('scope') != self.store_scope or not isinstance(request.get('id'),str) or not request['id']:
            raise ValueError('offline_request_required')
        hashed = selector.digest(request)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT input_hash,state FROM batches WHERE id=?',(request['id'],)).fetchone()
            if prior:
                if prior[0] != hashed: raise ValueError('batch_conflict')
                result = json.loads(prior[1])
                if selector.digest({k:v for k,v in result.items() if k!='state_hash'}) != result['state_hash']:
                    raise ValueError('invalid_previous_state')
            else:
                row = self.db.execute('SELECT state FROM batches ORDER BY rowid DESC LIMIT 1').fetchone()
                result = self.reduce(json.loads(row[0]) if row else None,request)
                self.db.execute('INSERT INTO batches VALUES (?,?,?)',
                                (request['id'],hashed,json.dumps(result,allow_nan=False)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            if self.db.in_transaction: self.db.execute('ROLLBACK')
            raise


def reconcile(previous, estimate, history, *, start, as_of):
    origin, cutoff = selector.timestamp(start), selector.timestamp(as_of)
    synthetic = estimate.get('scope') == 'SYNTHETIC_FUNDING_ESTIMATE_ONLY'
    if cutoff < origin or estimate.get('scope') not in ('FUNDING_ESTIMATE_DIAGNOSTIC_ONLY','SYNTHETIC_FUNDING_ESTIMATE_ONLY'):
        raise ValueError('invalid_reconciliation_input')
    if not history or selector.timestamp(history[0]['at']) != origin:
        raise ValueError('initial_position_history_required')
    last = None
    for row in history:
        at = selector.timestamp(row['at'])
        if at > cutoff or (last is not None and at <= last):
            raise ValueError('invalid_position_history_time')
        if set(row['positions']) != set(accounting.ARMS):
            raise ValueError('all_arms_required')
        for positions in row['positions'].values():
            if not set(positions) <= set(selector.UNIVERSE):
                raise ValueError('position_symbol')
            for quantity in positions.values(): accounting.number(quantity)
        last = at
    if previous is not None:
        body = {k:v for k,v in previous.items() if k != 'state_hash'}
        if previous.get('scope') != SCOPE or selector.digest(body) != previous.get('state_hash'):
            raise ValueError('invalid_previous_state')
        if previous['start'] != start or selector.timestamp(previous['as_of']) > cutoff:
            raise ValueError('reconciliation_identity_or_time')
        if previous.get('input_scope', 'FUNDING_ESTIMATE_DIAGNOSTIC_ONLY') != estimate['scope']:
            raise ValueError('funding_input_scope_changed')
        # Already observed positions cannot be rewritten on restart.
        if history[:len(previous['history'])] != previous['history']:
            raise ValueError('position_history_rewritten')
    entries = copy.deepcopy(previous['entries']) if previous else {}
    adjustments = []
    for event in estimate['events']:
        when = selector.timestamp(event['at'])
        if when > cutoff: raise ValueError('future_settlement')
        # The new comparison starts flat; no charges from earlier experiments.
        if when <= origin: continue
        symbol = event['symbol']
        if symbol not in selector.UNIVERSE: raise ValueError('funding_symbol')
        rate = accounting.number(event['rate'])
        ident = selector.digest([symbol, when.isoformat()])
        prior = [row for row in history if selector.timestamp(row['at']) < when]
        quantities = {a:prior[-1]['positions'][a].get(symbol,0.) for a in accounting.ARMS}
        old = entries.get(ident)
        if old and (old['rate'] != rate or old['quantities'] != quantities):
            raise ValueError('funding_conflict')
        mark = event.get('mark')
        if mark is not None:
            accounting.number(mark, True)
            if event.get('status') != ('SYNTHETIC_TEST_MARK' if synthetic else 'ESTIMATED_PRIOR_BOOK_MIDPOINT'):
                raise ValueError('unsupported_mark_source')
            source = event.get('mark_source_hash','')
            if not isinstance(source,str) or len(source)!=64 or any(c not in '0123456789abcdef' for c in source):
                raise ValueError('mark_provenance_required')
            observed = selector.timestamp(event['mark_observed_at'])
            if observed >= when: raise ValueError('noncausal_mark')
        if old and old['mark'] is not None:
            if mark is not None and mark != old['mark']: raise ValueError('funding_conflict')
            continue
        if old and mark is None: continue
        amounts = {a: (-q*mark*rate if mark is not None else (0. if q==0 else None))
                   for a,q in quantities.items()}
        for value in amounts.values():
            if value is not None: accounting.number(value)
        entry = dict(symbol=symbol,settlement_at=when.isoformat(),rate=rate,mark=mark,
                     quantities=quantities,amounts=amounts,recognized_at=as_of,
                     mark_source_hash=event.get('mark_source_hash') if mark is not None else None,
                     status='ESTIMATED' if mark is not None else 'MARK_UNRESOLVED')
        entries[ident] = entry
        if mark is not None:
            adjustments.append(dict(id=ident,settlement_at=entry['settlement_at'],recognized_at=as_of,
                                    amounts=amounts,resolves_pending=old is not None))
    arms = {}
    for arm in accounting.ARMS:
        pending = [k for k,e in entries.items() if e['amounts'][arm] is None]
        arms[arm] = dict(known_estimated_funding=sum(e['amounts'][arm] for e in entries.values() if e['amounts'][arm] is not None),
                         unresolved_event_ids=sorted(pending),net_funding=None,net_equity_complete=False)
    result = dict(scope=SCOPE,input_scope=estimate['scope'],start=start,as_of=as_of,history=copy.deepcopy(history),entries=entries,
                  adjustments=adjustments,arms=arms,settlement_coverage='UNKNOWN',
                  execution_ready=False,risk_increase_allowed=False)
    result['state_hash'] = selector.digest(result)
    return result
