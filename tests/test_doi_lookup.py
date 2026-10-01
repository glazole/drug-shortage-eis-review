import unittest
from unittest.mock import patch

from evidence_pipeline.config import SourceConfig
from evidence_pipeline.sources.crossref import CrossrefAdapter
from evidence_pipeline.sources.openalex import OpenAlexAdapter
from evidence_pipeline.sources.pubmed import PubMedAdapter
from evidence_pipeline.sources.elsevier import ScopusAdapter
from evidence_pipeline.exceptions import SourceRequestError


class Http:
    def __init__(self, json_response=None, text=''):
        self.json_response = json_response
        self.text = text
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.json_response

    def get_text(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.text


class DoiLookupTests(unittest.TestCase):
    def test_openalex_reconstructs_abstract_and_encodes_doi(self):
        http = Http({'doi': 'https://doi.org/10.1234/a(b)', 'title': 'A', 'abstract_inverted_index': {'Drug': [0], 'shortages': [1]}})
        adapter = OpenAlexAdapter(SourceConfig(name='openalex'), contact_email='test@example.org', http_client=http)
        record = adapter.lookup_doi('10.1234/a(b)')
        self.assertEqual(record.abstract, 'Drug shortages')
        self.assertIn('10.1234%2Fa%28b%29', http.calls[0][0])

    def test_crossref_uses_exact_endpoint_and_strips_jats(self):
        http = Http({'message': {'DOI': '10.1234/test', 'title': ['A'], 'abstract': '<jats:p>Test text.</jats:p>'}})
        adapter = CrossrefAdapter(SourceConfig(name='crossref'), contact_email='test@example.org', http_client=http)
        self.assertEqual(adapter.lookup_doi('10.1234/test').abstract, 'Test text.')
        self.assertNotIn('query.bibliographic', http.calls[0][1]['params'])

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_scopus_meta_abs_xml_with_structured_abstract(self):
        xml = '<abstracts-retrieval-response xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"><coredata><dc:title>Drug shortages</dc:title><prism:doi>10.1234/test</prism:doi><dc:description><p>Background: Drug shortages.</p> <p>Results: Better sharing.</p></dc:description></coredata></abstracts-retrieval-response>'
        http = Http(text=xml)
        adapter = ScopusAdapter(SourceConfig(name='scopus', api_key_env='ELSEVIER_API_KEY'), contact_email='test@example.org', http_client=http)
        record = adapter.lookup_doi('10.1234/test')
        self.assertEqual(record.doi, '10.1234/test')
        self.assertEqual(record.abstract, 'Background: Drug shortages. Results: Better sharing.')
        self.assertEqual(http.calls[0][1]['headers']['Accept'], 'application/xml')
        self.assertIn('view=META_ABS', http.calls[0][0])

    @patch.dict('os.environ', {'ELSEVIER_API_KEY': 'test-key'})
    def test_scopus_error_xml_is_not_success(self):
        adapter = ScopusAdapter(SourceConfig(name='scopus', api_key_env='ELSEVIER_API_KEY'), contact_email='test@example.org', http_client=Http(text='<service-error/>'))
        with self.assertRaises(SourceRequestError):
            adapter.lookup_doi('10.1234/test')

    def test_pubmed_lookup_ignores_search_date_and_requires_exact_doi(self):
        xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>1</PMID><Article><ArticleTitle>Paper</ArticleTitle><Abstract><AbstractText>Correct abstract.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1234/test</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
        http = Http({'esearchresult': {'idlist': ['1']}}, text=xml)
        waits = []
        adapter = PubMedAdapter(SourceConfig(name='pubmed'), contact_email='test@example.org', http_client=http, sleep=waits.append)
        self.assertEqual(adapter.lookup_doi('10.1234/test').abstract, 'Correct abstract.')
        self.assertEqual(http.calls[0][1]['params']['term'], '"10.1234/test"[AID]')
        self.assertNotIn('mindate', http.calls[0][1]['params'])
        self.assertEqual(waits, [0.34])
        self.assertIsNone(adapter.lookup_doi('10.1234/wrong'))


class PaginationTests(unittest.TestCase):
    def test_openalex_follows_cursor_and_retains_total(self):
        class Pages(Http):
            def get_json(self, url, **kwargs):
                self.calls.append((url, kwargs))
                page = len(self.calls)
                return {"meta": {"count": 500, "next_cursor": "next" if page == 1 else None},
                        "results": [{"title": "Paper " + str(i)} for i in range(200 if page == 1 else 5)]}
        http = Pages()
        adapter = OpenAlexAdapter(SourceConfig(name="openalex"), contact_email="", http_client=http)
        self.assertEqual(len(adapter.search("drug shortages", limit=205)), 205)
        self.assertEqual(http.calls[1][1]["params"]["cursor"], "next")
        self.assertEqual(http.calls[1][1]["params"]["per-page"], 5)
        self.assertEqual(adapter.last_search_total, 500)

    @patch.dict("os.environ", {"ELSEVIER_API_KEY": "test-key"})
    def test_scopus_paginates_with_offset_and_retains_total(self):
        class Pages(Http):
            def get_json(self, url, **kwargs):
                self.calls.append((url, kwargs))
                count = kwargs["params"]["count"]
                return {"search-results": {"opensearch:totalResults": "100", "entry": [
                    {"dc:title": "Paper " + str(i), "prism:coverDate": "2026-01-01"} for i in range(count)]}}
        http = Pages()
        adapter = ScopusAdapter(SourceConfig(name="scopus", api_key_env="ELSEVIER_API_KEY"), contact_email="", http_client=http)
        self.assertEqual(len(adapter.search("TITLE-ABS-KEY(shortage)", limit=30)), 30)
        self.assertEqual([call[1]["params"]["start"] for call in http.calls], [0, 25])
        self.assertEqual(adapter.last_search_total, 100)
