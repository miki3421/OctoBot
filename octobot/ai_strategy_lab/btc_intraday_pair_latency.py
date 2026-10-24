"""Equivalent valuation query plan; frozen strategy and account engine unchanged.

Only the current five-minute as-of valuation is optimized. The row-id reverse
scan avoids sorting every eligible historical event through events_time.
All cutoff, acknowledgment and funding predicates remain byte-for-byte intact.
"""
from intraday_pair.runner import Pair as FrozenPair, engine, strict, canonical, digest, NS


class FastValuationPair(FrozenPair):
    def observe_grid(self, slot_ns):
        """Reconstruct one common cutoff; no state or quote published later leaks in.

        State must have a returned commit acknowledgment by cutoff. The book must
        have a common availability receipt by cutoff and be fresh at cutoff.
        Missing data remain incomplete. This is valuation, never an entry replay.
        """
        self._guard(); now=self.clock.sample()['utc_ns']
        if type(slot_ns) is not int or slot_ns% (300*NS) or not self.t0<=slot_ns<=self.t0+90*86400*NS or now<slot_ns:
            raise ValueError('valuation_cutoff')
        existing=self.db.execute('SELECT payload FROM observations WHERE slot_ns=?',(slot_ns,)).fetchone()
        if existing:return strict(existing[0])
        book=None
        for r in self.db.execute("SELECT payload FROM inputs WHERE kind='book' ORDER BY seq DESC"):
            v=strict(r[0])
            if v['proof']['observed_visible']['utc_ns']>slot_ns:continue
            candidates=[row for row in v['payload']['rows'] if row['received_ts_ns']<=slot_ns]
            if candidates:book=candidates[-1];break
        mid=(book['bid_price_1']+book['ask_price_1'])/2 if book and engine.fresh(book,slot_ns) else None
        values={}
        for name,e in self.engines.items():
            row=e.db.execute('''SELECT payload FROM events e NOT INDEXED JOIN acknowledgements a USING(seq)
                WHERE at_ns<=? AND commit_returned_ns<=? ORDER BY e.seq DESC LIMIT 1''',(slot_ns,slot_ns)).fetchone()
            state=strict(row[0])['state'] if row else None
            pending_funding=e.db.execute("SELECT 1 FROM funding WHERE status='PENDING' AND tau<=?",(slot_ns,)).fetchone()
            # A later reconciliation must not turn a provisional historical point
            # into a complete one: as-of state records the then-known cash/funding.
            pending_asof=e.db.execute("SELECT 1 FROM funding WHERE tau<=? AND (observed>? OR status='PENDING')",(slot_ns,slot_ns)).fetchone()
            complete=bool(state and mid is not None and not pending_funding and not pending_asof
                          and not state.get('funding_pending') and not state['integrity_halt'])
            eq=state['cash']+state['q']*(mid-state['entry']) if state and mid is not None else None
            values[name]=dict(at_ns=slot_ns,equity=eq,complete=complete,q=state['q'] if state else None)
        out=dict(slot_ns=slot_ns,observed_ns=now,mid=mid,accounts=values)
        with self.db:self.db.execute('INSERT INTO observations VALUES(?,?,?,?)',
            (slot_ns,now,canonical(out).decode(),digest(out)))
        return out
