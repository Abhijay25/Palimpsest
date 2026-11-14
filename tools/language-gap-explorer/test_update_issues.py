import unittest
from update_issues import criteria,issue_items,compact_diff
class UpdateIssueTests(unittest.TestCase):
 def event(self,lang='sv',before='There were 1000 people.',after='There were 1200 people.',target='en'):
  return dict(id='e',lang=lang,kind='prose',data={'changes':[dict(before=before,after=after,counterparts=[dict(lang=target,text='1000 people')])]},stamp='2020-01-01',after_rev=2,status='pending')
 def test_foreign_requires_target_counterpart(self):
  self.assertEqual(len(issue_items([self.event()], 'en')),1)
  self.assertEqual(issue_items([self.event(target='fi')],'en'),[])
 def test_local_numeric_without_foreign_references(self):
  issues=issue_items([self.event(lang='en')],'en')
  self.assertEqual(issues[0]['issue_type'],'local');self.assertEqual(issues[0]['changes'][0]['counterparts'],[])
 def test_small_local_wording_not_issue(self):
  self.assertEqual(issue_items([self.event(lang='en',before='A red house.',after='A blue house.')],'en'),[])
 def test_punctuation_not_issue(self):
  self.assertEqual(issue_items([self.event(before='Same text.',after='Same text!')],'en'),[])
 def test_negation_rule(self):
  self.assertIn('Negation changed',criteria(dict(before='It was recognized.',after='It was not recognized.'),'en'))
 def test_compact_diff_escapes_and_keeps_changes(self):
  html=str(compact_diff(' '.join(['word']*100)+' old',' '.join(['word']*100)+' <script>new</script>'))
  self.assertIn('diff-ellipsis',html);self.assertIn('<del>old</del>',html);self.assertNotIn('<script>',html)
 def test_formatting_excluded(self):
  row=self.event();row['kind']='formatting';self.assertEqual(issue_items([row],'en'),[])
if __name__=='__main__':unittest.main()
