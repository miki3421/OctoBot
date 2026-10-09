"""Exact funding coverage against an externally reviewed, pinned calendar.

Never derives a schedule from observed rates or a current interval field.
The pin is a deployment trust input; this module never creates that approval.
"""
from pathlib import Path
try:
    from . import v13_dynamic_data as data
except ImportError:
    import v13_dynamic_data as data


class CoverageVerifier:
    def __init__(self,path,expected_sha256):
        self.path=Path(path);self.pin=expected_sha256

    def calendar(self):
        data.capture.safe_path(self.path,0)
        raw=self.path.read_bytes()
        if data.capture.sha(raw)!=self.pin:raise ValueError('funding_calendar_pin')
        value=data.capture.decode(raw)
        if value.get('scope')!='REVIEWED_EXPLICIT_FUNDING_CALENDAR_V1':raise ValueError('funding_calendar_scope')
        start,end=map(data.selector.timestamp,(value['from'],value['to']))
        if start>=end or set(value['settlements'])!=set(data.selector.UNIVERSE):raise ValueError('funding_calendar_window')
        if not value.get('evidence_sha256') or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in value['evidence_sha256']):
            raise ValueError('funding_calendar_evidence')
        for times in value['settlements'].values():
            parsed=[data.selector.timestamp(t) for t in times]
            if parsed!=sorted(set(parsed)) or any(not start<t<=end for t in parsed):raise ValueError('funding_calendar_events')
        return value

    def verify(self,receipts,books,*,previous_at,as_of):
        calendar=self.calendar();end=data.selector.timestamp(as_of)
        start=data.selector.timestamp(previous_at or as_of)
        if not data.selector.timestamp(calendar['from'])<=start<=end<=data.selector.timestamp(calendar['to']):
            raise ValueError('funding_calendar_does_not_cover_interval')
        expected={(symbol,int(data.selector.timestamp(t).timestamp()*1000)) for symbol,times in calendar['settlements'].items()
                  for t in times if start<data.selector.timestamp(t)<=end}
        selected=[]
        for receipt in receipts:
            if data.selector.timestamp(receipt['received_at'])>end:continue
            selected.append(dict(receipt,events=[e for e in receipt['events']
                if start.timestamp()*1000<e['at']<=end.timestamp()*1000]))
        estimate=data.estimate_funding(selected,books,as_of=as_of,expected=sorted(expected),maximum_mark_age_seconds=900)
        if estimate['expected_schedule_match'] is not True:raise ValueError('funding_settlement_coverage_gap')
        if any(e['mark'] is None for e in estimate['events']):raise ValueError('funding_mark_unresolved')
        return dict(calendar_sha256=self.pin,interval={'from':previous_at,'to':as_of,'coverage_complete':True,'events':estimate['events']},estimate=estimate)
