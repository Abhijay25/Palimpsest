import unittest
from showcase_history import Prose,changes,asof_time
from review_view import section_groups
class ShowcaseTests(unittest.TestCase):
 def test_extracts_safe_prose_and_headings(self):
  p=Prose();p.feed('<h2>History</h2><p>In 1999<sup>1</sup>, a change.</p><table><tr><td>Excluded</td></tr></table><script>bad()</script><p>Next.</p>')
  self.assertEqual(p.text(),'## History\n\nIn 1999, a change.\n\nNext.')
 def test_no_future_counterpart(self):
  self.assertEqual(asof_time('2020-01-01T00:00:00Z','2025-01-01T00:00:00Z'),'2020-01-01T00:00:00Z')
  self.assertEqual(asof_time('2026-01-01T00:00:00Z','2025-01-01T00:00:00Z'),'2025-01-01T00:00:00Z')
 def test_change_numeric_and_deletion(self):
  self.assertEqual(changes('In 1999.','In 2000.'),[{'before':'In 1999.','after':'In 2000.'}])
  self.assertEqual(changes('Deleted.',''),[{'before':'Deleted.','after':''}])
 def test_paragraph_move_does_not_notify(self):
  self.assertEqual(changes('First.\n\nSecond.','Second.\n\nFirst.'),[])
 def test_formatting_only(self):self.assertEqual(changes('Same prose.','Same prose.'),[])
 def test_reversed_pair_merges_only_when_highlight_shared(self):
  a=dict(lang='en',quote='In 1999.',section='History',highlights=[dict(start=3,end=7)])
  b=dict(lang='sv',quote='Ar 2000.',section='History',highlights=[dict(start=3,end=7)])
  base=dict(category='conflict',title='Dates',evidence=[a,b])
  findings,_=section_groups([dict(base,id='a'),dict(base,id='b',evidence=[b,a])],['en','sv'])
  self.assertEqual(len(findings),1);self.assertEqual(len(findings[0]['supporting_judgments']),2)
 def test_html_is_escaped(self):
  from watchlist import diff_html
  self.assertNotIn('<script>',str(diff_html('old','<script>new</script>')))
if __name__=='__main__':unittest.main()
