import unittest
from types import SimpleNamespace
from unittest.mock import patch

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.diagnostics import probe_scopus
from evidence_pipeline.exceptions import HttpStatusError, SourceRequestError
from evidence_pipeline.models import WorkRecord


class ScopusDiagnosticTests(unittest.TestCase):
    def test_views_are_reported_with_effective_fallback_and_no_raw_errors(self):
        class Adapter:
            def __init__(self, config, **kwargs):
                self.config = config
            def search(self, query, limit):
                self.last_search_view = 'STANDARD'
                return [WorkRecord(title='Paper', doi='10.1234/test')]
            def lookup_doi(self, doi):
                try:
                    raise HttpStatusError(403, 'secret-key')
                except HttpStatusError as cause:
                    raise SourceRequestError('secret-key') from cause
        study = SimpleNamespace(sources={'scopus': SourceConfig(name='scopus')}, contact_email='')
        with patch('evidence_pipeline.diagnostics.ScopusAdapter', Adapter):
            result = probe_scopus(study, '10.1234/test')
        self.assertEqual([r['requested_view'] for r in result['results']], ['STANDARD', 'COMPLETE', 'META_ABS'])
        self.assertEqual(result['results'][1]['effective_view'], 'STANDARD')
        self.assertEqual(result['results'][2]['http_status'], 403)
        self.assertNotIn('secret-key', str(result))
