"""Offline ABC cash accounting for explicitly imported simulated fills.

No fill generation, order admission, grants or operational-store discovery.
Funding and cash are reduced and persisted as one state in one transaction.
"""
import copy
try:
    from . import v13_dynamic_funding as funding
except ImportError:
    import v13_dynamic_funding as funding

selector = funding.selector
accounting = funding.accounting
SCOPE = 'OFFLINE_ABC_CASH_IMPORT_V1'


def advance(previous, request):
    if request.get('scope') != SCOPE:
        raise ValueError('offline_cash_scope_required')
    start, now = request['start'], request['as_of']
    origin, cutoff = selector.timestamp(start), selector.timestamp(now)
    if cutoff < origin: raise ValueError('before_start')
    if previous:
        if (previous.get('scope') != SCOPE or
                selector.digest({k:v for k,v in previous.items() if k!='state_hash'}) != previous.get('state_hash')):
            raise ValueError('invalid_cash_state')
        if previous['start'] != start or cutoff < selector.timestamp(previous['as_of']):
            raise ValueError('cash_identity_or_time')
        result = copy.deepcopy(previous)
    else:
        result = dict(scope=SCOPE,start=start,as_of=start,fills={},funding=None,
                      arms={a:dict(cash=10000.,fees=0.,positions={},funding=0.) for a in accounting.ARMS},
                      history=[dict(at=start,positions={a:{} for a in accounting.ARMS})])
    last = selector.timestamp(result['as_of'])
    fills = sorted(request['fills'],key=lambda f:(selector.timestamp(f['at']),f['id']))
    for fill in fills:
        if fill.get('scope') != 'SIMULATED_FILL_IMPORT_ONLY': raise ValueError('simulated_fill_required')
        ident = fill['id']
        if not isinstance(ident,str) or not ident: raise ValueError('fill_identity')
        canonical = dict(fill,at=selector.timestamp(fill['at']).isoformat())
        hashed = selector.digest(canonical)
        if ident in result['fills']:
            if result['fills'][ident] != hashed: raise ValueError('fill_conflict')
            continue
        when = selector.timestamp(fill['at'])
        if not last < when <= cutoff: raise ValueError('late_or_future_fill')
        arm, symbol = fill['arm'], fill['symbol']
        if arm not in accounting.ARMS or symbol not in selector.UNIVERSE:
            raise ValueError('fill_account_or_symbol')
        quantity = accounting.number(fill['quantity'])
        price = accounting.number(fill['price'],True)
        fee = accounting.number(fill['fee'])
        if not quantity or fee < 0: raise ValueError('fill_quantity_or_fee')
        account = result['arms'][arm]
        account['cash'] -= quantity*price + fee
        account['fees'] += fee
        account['positions'][symbol] = account['positions'].get(symbol,0.) + quantity
        result['fills'][ident] = hashed
        snapshot = dict(at=when.isoformat(),positions={a:copy.deepcopy(result['arms'][a]['positions']) for a in accounting.ARMS})
        if selector.timestamp(result['history'][-1]['at']) == when:
            result['history'][-1] = snapshot
        else: result['history'].append(snapshot)
    reconciled = funding.reconcile(result['funding'],request['estimate'],result['history'],start=start,as_of=now)
    for arm, account in result['arms'].items():
        delta = sum(e['amounts'][arm] for e in reconciled['adjustments'])
        account['cash'] += delta
        account['funding'] += delta
        for key in ('cash','fees','funding'): accounting.number(account[key])
        for quantity in account['positions'].values(): accounting.number(quantity)
        # Do not present a complete balance while settlement coverage is unknown.
        account['net_equity'] = None
        account['funding_complete'] = False
    result.update(as_of=now,funding=reconciled,execution_ready=False,risk_increase_allowed=False)
    result.pop('state_hash',None)
    result['state_hash'] = selector.digest(result)
    return result


class CashStore(funding.OfflineStore):
    store_scope = SCOPE

    def reduce(self, previous, request):
        return advance(previous,request)
