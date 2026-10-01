import unittest
from unittest.mock import patch

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.exceptions import HttpStatusError, SourceRequestError
from evidence_pipeline.sources.elsevier import ScopusAdapter


class FakeHttp:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append(kwargs | {"params": dict(kwargs["params"])})
        value = next(self.replies)
        if isinstance(value, Exception):
            raise value
        return value


def page(title='Drug shortages', total=1):
    return {'search-results': {'opensearch:totalResults': str(total), 'entry': [{'dc:title': title, 'prism:coverDate': '2026-01-01'}]}}


class ScopusTests(unittest.TestCase):
    def adapter(self, http, view='STANDARD'):
        return ScopusAdapter(SourceConfig(name='scopus', api_key_env='ELSEVIER_API_KEY', options={'view': view, 'year': '2021-2026'}), contact_email='test@example.org', http_client=http)

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key', 'ELSEVIER_INSTTOKEN': 'test-token'})
    def test_standard_date_token_and_mapping(self):
        http = FakeHttp([page()])
        records = self.adapter(http).search('TITLE-ABS-KEY(drug)', limit=20)
        self.assertEqual(records[0].year, 2026)
        self.assertEqual(http.calls[0]['params']['view'], 'STANDARD')
        self.assertEqual(http.calls[0]['params']['date'], '2021-2026')
        self.assertEqual(http.calls[0]['headers']['X-ELS-Insttoken'], 'test-token')

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_complete_403_fallback_remains_standard_on_next_page(self):
        http = FakeHttp([HttpStatusError(403, 'not entitled'), page(total=2), page('Drug supply', total=2)])
        self.assertEqual(len(self.adapter(http, 'COMPLETE').search('query', limit=2)), 2)
        self.assertEqual([c['params']['view'] for c in http.calls], ['COMPLETE', 'STANDARD', 'STANDARD'])
        self.assertEqual(http.calls[-1]['params']['start'], 1)

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_auth_failure_reports_actionable_diagnostic_without_key(self):
        http = FakeHttp([HttpStatusError(401, 'invalid key')])
        with self.assertRaisesRegex(SourceRequestError, 'ELSEVIER_API_KEY') as result:
            self.adapter(http).search('query', limit=20)
        self.assertNotIn('test-key', str(result.exception))
        self.assertEqual(len(http.calls), 1)

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_error_payload_is_not_success(self):
        with self.assertRaises(SourceRequestError):
            self.adapter(FakeHttp([{'service-error': {'status': 'INVALID_INPUT'}}])).search('query', limit=20)

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_zero_results_sentinel(self):
        http = FakeHttp([{'search-results': {'opensearch:totalResults': '0', 'entry': [{'error': 'Result set was empty'}]}}])
        self.assertEqual(self.adapter(http).search('query', limit=20), [])
