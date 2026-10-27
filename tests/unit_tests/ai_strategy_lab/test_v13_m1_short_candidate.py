"""The prepared adapter must refuse operating paths before opening a ledger."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from octobot.ai_strategy_lab import v13_m1_short_candidate as c

ROOT=Path(__file__).resolve().parents[3]
P=ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json'


class OfflineGuardTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)/'audit-evidence/work';self.root.mkdir(parents=True)
        self.marker=self.root/'OFFLINE_ONLY.json';self.marker.write_text(json.dumps(dict(
            scope='OFFLINE_COPY_NO_OPERATING_AUTHORITY',protocol_id=c.risk.PROTOCOL_ID,
            account='v13-m1-short-paper-v1-5e761f0cedac',source_sha256='a'*64)));self.marker.chmod(0o444)
        for name in ('seed','original'):
            p=self.root/(name+'.sqlite');p.write_bytes(b'guard-only-control');p.chmod(0o444)
        self.cfg=dict(db=str(self.root/'copy.sqlite'),output=str(self.root/'output.json'),
            management=dict(projection=str(self.root/'management.json')),
            original=str(self.root/'original.sqlite'),seed=str(self.root/'seed.sqlite'),
            short_candidate=dict(scope='OFFLINE_QUALIFICATION_ONLY',work_root=str(self.root),protocol=str(P)))

    def test_offline_guard_accepts_only_marked_read_only_sources(self):
        p,_=c.guard(self.cfg);self.assertEqual(p['protocol_id'],c.risk.PROTOCOL_ID)

    def test_no_live_mode_or_unmarked_operating_root(self):
        bad=copy.deepcopy(self.cfg);bad['short_candidate']['scope']='PRODUCTION'
        with self.assertRaisesRegex(ValueError,'offline_work_copy'):c.guard(bad)
        bad=copy.deepcopy(self.cfg);bad['short_candidate']['work_root']='/root/auto_trading_sys/octobot-local/v13-m1-paper-v1'
        with self.assertRaisesRegex(ValueError,'offline_work_copy'):c.guard(bad)

    def test_write_paths_cannot_escape_via_plain_path_or_symlink(self):
        for key in ('db','output'):
            bad=copy.deepcopy(self.cfg);bad[key]=str(Path(self.folder.name)/'outside.sqlite')
            with self.assertRaisesRegex(ValueError,'outside_work_copy'):c.guard(bad)
        link=self.root/'link';link.symlink_to(self.folder.name,target_is_directory=True)
        bad=copy.deepcopy(self.cfg);bad['db']=str(link/'outside.sqlite')
        with self.assertRaisesRegex(ValueError,'outside_work_copy'):c.guard(bad)

    def test_writable_source_is_rejected(self):
        Path(self.cfg['original']).chmod(0o644)
        with self.assertRaisesRegex(ValueError,'read_only_source_copy'):c.guard(self.cfg)

    def test_writable_or_wrong_account_marker_is_rejected(self):
        self.marker.chmod(0o644)
        with self.assertRaisesRegex(ValueError,'sealed_work_marker'):c.guard(self.cfg)
        v=json.loads(self.marker.read_text());v['account']='other';self.marker.write_text(json.dumps(v));self.marker.chmod(0o444)
        with self.assertRaisesRegex(ValueError,'work_copy_identity'):c.guard(self.cfg)


if __name__=='__main__':unittest.main()
