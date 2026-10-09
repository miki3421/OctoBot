"""Guarded, local-only ABC consumer. No services, grants or network calls.

Production entry takes an intent identifier, never a caller-authored PASS or
packet. Admission and funding verification run before any ledger is opened.
Current admission deliberately denies activation and unresolved funding.
"""
import json
import math
import time
import datetime as dt
from pathlib import Path
try:
    from . import v13_dynamic_admission as admission
    from . import v13_dynamic_cash as cash
    from . import v13_dynamic_data as data
    from . import v13_dynamic_forward as forward
    from . import v13_dynamic_coverage as coverage
except ImportError:
    import v13_dynamic_admission as admission
    import v13_dynamic_cash as cash
    import v13_dynamic_data as data
    import v13_dynamic_forward as forward
    import v13_dynamic_coverage as coverage

SCOPE='OFFLINE_ABC_VERIFIED_RECEIPT_LEDGER_V1'
CONTRACT_SCOPE='APPROVED_ABC_RESEARCH_SIMULATION'


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class AdmissionDenied(ValueError):
    def __init__(self,reasons):
        self.reasons=list(reasons)
        super().__init__(';'.join(self.reasons))


def _reduce(previous, packet, funding, *, observation=False, protective=False):
    """Internal accounting after trusted admission, not a public grant API."""
    selector=cash.selector;engine=cash.accounting
    if packet.get('scope')!='REAL_ABC_EXECUTION_INPUT_PREFLIGHT_V1':raise ValueError('real_packet_required')
    if selector.digest({k:v for k,v in packet.items() if k!='packet_hash'})!=packet.get('packet_hash'):
        raise ValueError('packet_integrity')
    checked=data.admit_books(list(packet['books'].values()),intent_persisted_at=packet['intent_persisted_at'],as_of=packet['as_of'])
    decision=packet['derived']['selection']
    if packet['intent_id']!=decision['decision_id']:raise ValueError('intent_binding')
    if selector.timestamp(packet['intent_persisted_at'])<selector.timestamp(decision['slot']):
        raise ValueError('intent_before_decision')
    if previous:
        if previous.get('scope')!=SCOPE or selector.digest({k:v for k,v in previous.items() if k!='state_hash'})!=previous.get('state_hash'):
            raise ValueError('ledger_integrity')
        state=previous['engine']
    else:
        state=engine.initial_state();state['scope']=SCOPE
    books=checked['books']
    # Re-derive precision from verified books rather than trusting redundant maps.
    tick=dict(id=packet['intent_id'],scope=SCOPE,at=packet['as_of'],decision_at=decision['slot'],
              selection=decision,covariance=packet['derived']['covariance'],targets=packet['derived']['targets'],
              contract_scope=CONTRACT_SCOPE,books={s:dict(at=b['at'],bids=b['bids'],asks=b['asks']) for s,b in books.items()},
              marks={s:(b['bids'][0][0]+b['asks'][0][0])/2 for s,b in books.items()},
              price_ticks={s:float(b['precision']['price_tick']) for s,b in books.items()},
              quantity_steps={s:float(b['precision']['quantity_increment']) for s,b in books.items()},
              fee_rate=.0006,fee_rates={s:float(b['precision']['public_taker_fee']) for s,b in books.items()},
              funding=funding['interval'],delayed_funding=funding.get('delayed_events',[]))
    if protective:
        if observation or previous is None:raise ValueError('protective_account_required')
        tick.pop('selection');tick.pop('covariance')
        tick.update(targets={a:{} for a in engine.ARMS},protective_only=True,decision_at=packet['intent_persisted_at'])
    if observation:
        if previous is None:raise ValueError('observation_requires_account')
        for key in ('selection','covariance','targets'):tick.pop(key)
    updated,trades=engine._advance(state,tick,expected_scope=SCOPE,contract_scope=CONTRACT_SCOPE)
    imports=[dict(scope='SIMULATED_FILL_IMPORT_ONLY',id=selector.digest([packet['packet_hash'] if protective else packet['intent_id'],i]),at=packet['as_of'],
                  **{k:t[k] for k in ('arm','symbol','quantity','price','fee')}) for i,t in enumerate(trades)]
    ledger=cash.advance(previous['cash'] if previous else None,dict(scope=cash.SCOPE,start=decision['start'],
                        as_of=packet['as_of'],fills=imports,estimate=funding['estimate']))
    for arm in engine.ARMS:
        for field in ('cash','funding','fees'):
            if not math.isclose(updated['arms'][arm][field],ledger['arms'][arm][field],rel_tol=1e-12,abs_tol=1e-8):
                raise ValueError('accounting_divergence')
        for symbol in set(updated['arms'][arm]['positions'])|set(ledger['arms'][arm]['positions']):
            if not math.isclose(updated['arms'][arm]['positions'].get(symbol,0),ledger['arms'][arm]['positions'].get(symbol,0),rel_tol=1e-12,abs_tol=1e-10):
                raise ValueError('position_divergence')
    result=dict(scope=SCOPE,engine=updated,cash=ledger,trades=trades,packet_hash=packet['packet_hash'],
                performance_evidence=False,orders_authorized=False,equity_complete=updated.get('equity_complete',False))
    result['state_hash']=selector.digest(result)
    return result


class _Ledger(cash.funding.OfflineStore):
    store_scope=SCOPE

    def reduce(self,previous,request):
        return _reduce(previous,request['packet'],request['funding'])


class Consumer:
    def __init__(self,*,repo,approval_path,approval_sha256,archive,activation,intents,ledger_path,
                 forward_path=None,forward_uid=None,calendar_path=None,calendar_sha256=None):
        self.repo=repo;self.approval_path=approval_path;self.approval_sha256=approval_sha256
        self.archive=archive;self.activation=activation;self.intents=intents;self.ledger_path=Path(ledger_path)
        self.forward_path=forward_path;self.forward_uid=forward_uid
        self.calendar=coverage.CoverageVerifier(calendar_path,calendar_sha256) if calendar_path is not None else None

    def readiness(self):
        return admission.inspect(self.repo,self.approval_path,self.approval_sha256,self.archive,self.activation)

    def consume(self,intent_id,*,valid_until=None):
        verdict=self.readiness()
        if verdict.get('execution_ready') is not True or verdict.get('blockers'):
            raise AdmissionDenied(verdict.get('blockers') or ['execution_not_authorized'])
        # Funding precondition is checked before creating/opening a writable
        # ledger. Both dependencies must be configured and verifiable.
        self._funding_available()
        records=self._read_books()
        packet=self.intents.execution_inputs(intent_id,records)
        store=_Ledger(self.ledger_path,create=not self.ledger_path.exists())
        try:
            store.db.execute('BEGIN IMMEDIATE')
            old=store.db.execute('SELECT state FROM batches WHERE id=?',(intent_id,)).fetchone()
            if old:
                result=json.loads(old[0])
                if cash.selector.digest({k:v for k,v in result.items() if k!='state_hash'})!=result.get('state_hash'):
                    raise ValueError('ledger_integrity')
                store.db.execute('COMMIT')
                return result
            if valid_until is not None and data.selector.timestamp(utc_now()) >= data.selector.timestamp(valid_until):
                raise ValueError('intent_expired_under_writer_lock')
            latest=store.db.execute('SELECT state FROM batches ORDER BY rowid DESC LIMIT 1').fetchone()
            previous=json.loads(latest[0]) if latest else None
            funding=self._verified_funding(previous,packet)
            # A packet checked before waiting for the writer lock may expire.
            data.admit_books(list(packet['books'].values()),intent_persisted_at=packet['intent_persisted_at'],
                             as_of=utc_now())
            result=_reduce(previous,packet,funding)
            store.db.execute('INSERT INTO batches VALUES (?,?,?)',(intent_id,packet['packet_hash'],json.dumps(result,allow_nan=False)))
            store.db.execute('COMMIT')
            return result
        except BaseException:
            if store.db.in_transaction:store.db.execute('ROLLBACK')
            raise
        finally:store.close()

    def observe(self):
        return self._observe_or_close()

    def close_all(self,command_path,expected_sha256):
        data.capture.safe_path(command_path,0)
        raw=Path(command_path).read_bytes()
        if data.capture.sha(raw)!=expected_sha256:raise ValueError('admin_command_pin')
        command=json.loads(raw)
        if command.get('scope')!='ABC_ADMIN_CLOSE_ALL_V1' or not command.get('id'):
            raise ValueError('admin_command_scope')
        if Path(command['ledger_path']).resolve()!=self.ledger_path.resolve():raise ValueError('admin_account_binding')
        return self._observe_or_close(command)

    def _observe_or_close(self,command=None):
        """Persist marked equity/risk/funding without strategy decisions or fills.

        Uses the same ledger writer lock as consumption. Never creates an account.
        Missing funding denies the complete-equity observation, not a zero cost.
        """
        # Root-authenticated, state-bound reduction commands are independent
        # of the strategy's permission to add risk. They still require custody,
        # current books, persistence and exact account-generation matching.
        if command is None:
            verdict=self.readiness()
            if verdict.get('execution_ready') is not True or verdict.get('blockers'):
                raise AdmissionDenied(verdict.get('blockers') or ['execution_not_authorized'])
        self._funding_available()
        if not self.ledger_path.exists():raise ValueError('observation_requires_account')
        records=self._read_books();store=_Ledger(self.ledger_path)
        try:
            store.db.execute('BEGIN IMMEDIATE')
            row=store.db.execute('SELECT state FROM batches ORDER BY rowid DESC LIMIT 1').fetchone()
            if row is None:raise ValueError('observation_requires_account')
            previous=json.loads(row[0]);selection=previous['engine']['selection']
            at=utc_now()
            if command is not None:
                if not data.selector.timestamp(command['issued_at'])<=data.selector.timestamp(at)<data.selector.timestamp(command['expires_at']):
                    raise ValueError('admin_command_expired')
                if command['expected_state_hash']!=previous['state_hash']:raise ValueError('admin_position_generation_changed')
                if store.db.execute('SELECT 1 FROM batches WHERE id=?',('admin:'+command['id'],)).fetchone():
                    raise ValueError('admin_command_replay')
            persisted=command['issued_at'] if command is not None else previous['engine']['last_at']
            admitted=data.admit_books(records,intent_persisted_at=persisted,as_of=at)
            packet=dict(scope='REAL_ABC_EXECUTION_INPUT_PREFLIGHT_V1',intent_id=selection['decision_id'],
                        intent_persisted_at=persisted,as_of=at,
                        derived=dict(selection=selection,covariance=[],targets={}),books=admitted['books'])
            packet['packet_hash']=cash.selector.digest(packet)
            try:funding=self._verified_funding(previous,packet)
            except ValueError as exc:
                if command is None or str(exc) not in ('funding_settlement_coverage_gap','funding_mark_unresolved'):
                    raise
                funding=dict(interval={'from':previous['engine'].get('funding_cursor',previous['engine']['last_at']),
                                       'to':at,'coverage_complete':False,'events':[]},
                             estimate={'scope':'FUNDING_ESTIMATE_DIAGNOSTIC_ONLY','events':[]})
            if command is not None and data.selector.timestamp(utc_now())>=data.selector.timestamp(command['expires_at']):
                raise ValueError('admin_command_expired')
            result=_reduce(previous,packet,funding,observation=command is None,protective=command is not None)
            key=('admin:'+command['id']) if command is not None else 'observation:'+cash.selector.digest([previous['state_hash'],packet['packet_hash']])
            store.db.execute('INSERT INTO batches VALUES (?,?,?)',(key,packet['packet_hash'],json.dumps(result,allow_nan=False)))
            store.db.execute('COMMIT');return result
        except BaseException:
            if store.db.in_transaction:store.db.execute('ROLLBACK')
            raise
        finally:store.close()

    def _read_books(self):
        source=self._forward();now=time.time();day=now//86400*86400
        try:return source.read(day,now,kinds=('books',))
        finally:source.close()

    def _forward(self):
        if self.forward_path is None or type(self.forward_uid) is not int:
            raise AdmissionDenied(['forward_source_not_configured'])
        data.store_path(self.forward_path,self.forward_uid)
        return forward.ForwardArchive(self.forward_path,self.repo)

    def _funding_available(self):
        if self.calendar is None:raise AdmissionDenied(['funding_coverage_verifier_unavailable'])
        self.calendar.calendar()
        source=self._forward();source.close()

    def _verified_funding(self,previous,packet):
        if self.calendar is None:raise AdmissionDenied(['funding_coverage_verifier_unavailable'])
        previous_at=previous['engine'].get('funding_cursor',previous['engine']['last_at']) if previous else None
        if previous_at is None:
            # Newly created accounts are flat before their first fill. No
            # pre-start debt is inherited, but the calendar must cover now.
            return self.calendar.verify([],[],previous_at=None,as_of=packet['as_of'])
        end=data.capture.utc(packet['as_of']);start=data.capture.utc(previous_at)
        source=self._forward();records=[]
        try:
            day=start//86400*86400
            while day<=end//86400*86400:
                records.extend(source.read(day,end,kinds=('funding','books')));day+=86400
        finally:source.close()
        return self.calendar.verify([r for r in records if r['kind']=='funding'],[r for r in records if r['kind']=='books'],
                                    previous_at=previous_at,as_of=packet['as_of'])
