"""Database-free HTML contract check for the article-tabs fixture."""
import os
from app import app
def main():
    os.environ['LANGGAP_FIXTURES']='1'
    with app.test_client() as client: page=client.get('/article/Q-demo?tab=flags').get_data(as_text=True)
    missing=[item for item in ('role="tablist"','aria-current="page"','id="language-panel"','id="flags-panel"','id="flags-revision"','Scan 3 revisions','Re-scan (fresh)','Page consistency','Check this page','flags-summary-bar','flags-workspace','flags-diff-pane','flags-rail','Prior revision','Selected revision','data-diff-side="old"','data-diff-side="new"') if item not in page]
    if missing: raise SystemExit('article UI contract missing: '+', '.join(missing))
    print('article UI fixture contract passed')
if __name__=='__main__': main()
