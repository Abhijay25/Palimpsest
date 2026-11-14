"""Persistent, bidirectional passage links and revision-driven review notices.

Change detection and review never invoke a model. Semantic discovery is explicit.
Snapshot articles remain immutable; sandbox/imported revisions live separately.
"""
import argparse,copy,difflib,hashlib,json,re,uuid
from markupsafe import Markup,escape
from core import connect

class StaleRevision(ValueError):pass

def init():
    with connect() as db,db.cursor() as c:
        for sql in [
          '''CREATE TABLE IF NOT EXISTS watched_document(id INT AUTO_INCREMENT PRIMARY KEY,
            topic VARCHAR(24),lang CHAR(2),page_id INT,title VARCHAR(255),current_revision INT,
            UNIQUE KEY topic_lang(topic,lang)) CHARACTER SET utf8mb4''',
          '''CREATE TABLE IF NOT EXISTS watched_revision(id INT AUTO_INCREMENT PRIMARY KEY,
            document_id INT,parent_id INT,upstream_id VARCHAR(100),kind VARCHAR(30),label VARCHAR(255),
            text MEDIUMTEXT,sha256 CHAR(64),created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            KEY(document_id)) CHARACTER SET utf8mb4''',
          '''CREATE TABLE IF NOT EXISTS watched_link(id CHAR(32) PRIMARY KEY,topic VARCHAR(24),
            title VARCHAR(255),note TEXT,state LONGTEXT,identity_key CHAR(64) UNIQUE,
            provenance VARCHAR(30),active BOOL DEFAULT 1,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,KEY(topic)) CHARACTER SET utf8mb4''',
          '''CREATE TABLE IF NOT EXISTS watched_notice(id CHAR(32) PRIMARY KEY,link_id CHAR(32),
            changed_revision INT,lang CHAR(2),kind VARCHAR(40),status VARCHAR(30),payload LONGTEXT,
            review_note TEXT,check_result LONGTEXT,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed TIMESTAMP NULL,UNIQUE KEY revision_link(link_id,changed_revision)) CHARACTER SET utf8mb4''',
          '''CREATE TABLE IF NOT EXISTS watched_review(id CHAR(32) PRIMARY KEY,notice_id CHAR(32),
            action VARCHAR(30),note TEXT,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP) CHARACTER SET utf8mb4''']:
            c.execute(sql)

def sha(text):return hashlib.sha256(text.encode()).hexdigest()
def canonical(text):return re.sub(r'\s+',' ',text).strip()

def ensure_topic(topic):
    with connect() as db,db.cursor() as c:
        db.begin()
        try:
            c.execute('SELECT * FROM article WHERE wikidata_id=%s',(topic,));aa=c.fetchall()
            if not aa:raise ValueError('Unknown topic.')
            for a in aa:
                c.execute('INSERT IGNORE INTO watched_document(topic,lang,page_id,title) VALUES (%s,%s,%s,%s)',
                  (topic,a['lang'],a['page_id'],a['title']))
                c.execute('SELECT * FROM watched_document WHERE topic=%s AND lang=%s FOR UPDATE',(topic,a['lang']));doc=c.fetchone()
                if doc['current_revision'] is None:
                    c.execute('INSERT INTO watched_revision(document_id,upstream_id,kind,label,text,sha256) VALUES (%s,%s,\'snapshot\',%s,%s,%s)',
                      (doc['id'],str(a['rev_id']),'Wikipedia snapshot revision '+str(a['rev_id']),a['text'],sha(a['text'])))
                    c.execute('UPDATE watched_document SET current_revision=%s WHERE id=%s',(c.lastrowid,doc['id']))
            db.commit()
        except Exception:db.rollback();raise
    return documents(topic)

def documents(topic):
    with connect() as db,db.cursor() as c:
        c.execute('''SELECT d.*,r.text,r.kind,r.label,r.upstream_id FROM watched_document d
          JOIN watched_revision r ON r.id=d.current_revision WHERE d.topic=%s ORDER BY d.lang''',(topic,))
        return {r['lang']:r for r in c.fetchall()}

def create_link(topic,selections,title,note,provenance='editor_confirmed'):
    if len(selections)<2 or len({s['lang'] for s in selections})!=len(selections):
        raise ValueError('Choose one passage in each of two or three different languages.')
    ensure_topic(topic)
    with connect() as db,db.cursor() as c:
        db.begin()
        try:
            c.execute('''SELECT d.*,r.text FROM watched_document d JOIN watched_revision r ON r.id=d.current_revision
              WHERE d.topic=%s ORDER BY d.id FOR UPDATE''',(topic,));docs={d['lang']:d for d in c.fetchall()}
            state=[]
            for s in selections:
                doc=docs.get(s['lang']);quote=s['quote'].strip()
                if not doc or not quote or len(quote)>12000 or doc['text'].count(quote)!=1:
                    raise ValueError('Each passage must be an exact, unique excerpt of the current local revision.')
                if int(s.get('revision',doc['current_revision']))!=doc['current_revision']:
                    raise StaleRevision('A revision changed while you were confirming the link. Refresh and review again.')
                start=doc['text'].find(quote)
                state.append(dict(lang=s['lang'],document_id=doc['id'],title=doc['title'],
                  baseline_revision=doc['current_revision'],baseline_text=quote,current_revision=doc['current_revision'],
                  current_text=quote,start=start,end=start+len(quote),valid=True))
            identity=sha(json.dumps(sorted((s['lang'],s['baseline_text']) for s in state),ensure_ascii=False))
            identity=sha(topic+identity)
            c.execute('SELECT id FROM watched_link WHERE identity_key=%s',(identity,));existing=c.fetchone()
            if existing:db.commit();return existing['id']
            identity_id=uuid.uuid4().hex
            c.execute('INSERT INTO watched_link(id,topic,title,note,state,identity_key,provenance) VALUES (%s,%s,%s,%s,%s,%s,%s)',
              (identity_id,topic,title[:255] or 'Linked passages',note[:4000],json.dumps(state),identity,provenance))
            db.commit();return identity_id
        except Exception:db.rollback();raise

def relocate(old,new,side):
    quote=side['current_text']
    if quote and new.count(quote)==1:
        start=new.index(quote);return start,start+len(quote),True
    if quote and new.count(quote)>1:return side['start'],side['end'],False
    if not side['valid']:return side['start'],side['end'],False
    opcodes=difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes()
    def project(pos,right=False):
        for tag,a,b,x,y in opcodes:
            if a<=pos<=b:
                if tag=='equal':return x+pos-a
                if tag=='insert':return y if right else x
                if pos==a:return x
                if pos==b:return y
                return y if right else x
        return len(new)
    start,end=project(side['start']),project(side['end'],True)
    return start,end,start<end and bool(new[start:end].strip())

def change_kind(before,after,valid):
    if not valid:return 'link_needs_review'
    if re.findall(r'\d+(?:[.,]\d+)*',before)!=re.findall(r'\d+(?:[.,]\d+)*',after):return 'value_changed'
    return 'passage_changed'

def ingest(topic,lang,text,base_revision,kind='sandbox',label='Local sandbox edit',upstream_id=None):
    if not text.strip() or len(text)>2_000_000:raise ValueError('Revision text must contain 1–2,000,000 characters.')
    if kind not in ('sandbox','imported'):raise ValueError('Unsupported revision source.')
    ensure_topic(topic)
    with connect() as db,db.cursor() as c:
        db.begin()
        try:
            c.execute('''SELECT d.*,r.text FROM watched_document d JOIN watched_revision r ON r.id=d.current_revision
              WHERE topic=%s AND lang=%s FOR UPDATE''',(topic,lang));doc=c.fetchone()
            if not doc:raise ValueError('This language is absent from the topic.')
            if doc['current_revision']!=int(base_revision):raise StaleRevision('A newer local revision exists. Refresh before editing.')
            if text==doc['text']:db.commit();return doc['current_revision'],0
            c.execute('INSERT INTO watched_revision(document_id,parent_id,kind,label,text,sha256,upstream_id) VALUES (%s,%s,%s,%s,%s,%s,%s)',
              (doc['id'],doc['current_revision'],kind,label[:255],text,sha(text),upstream_id))
            revision=c.lastrowid
            c.execute('UPDATE watched_document SET current_revision=%s WHERE id=%s',(revision,doc['id']))
            c.execute('SELECT * FROM watched_link WHERE topic=%s AND active=1 ORDER BY id FOR UPDATE',(topic,));links=c.fetchall()
            count=0
            for link in links:
                state=json.loads(link['state']);side=next((s for s in state if s['lang']==lang),None)
                if not side:continue
                previous=copy.deepcopy(side)
                start,end,valid=relocate(doc['text'],text,side)
                current=text[start:end] if valid else ''
                side.update(start=start,end=end,valid=valid,current_text=current,current_revision=revision)
                c.execute('UPDATE watched_link SET state=%s WHERE id=%s',(json.dumps(state),link['id']))
                if valid and canonical(previous['current_text'])==canonical(current):continue
                # Keep every event in history, but only the newest unresolved change per link is active.
                c.execute("UPDATE watched_notice SET status='superseded' WHERE link_id=%s AND status IN ('pending','needs_update')",(link['id'],))
                payload={'before':previous['current_text'],'after':current,'baseline':previous['baseline_text'],
                  'baseline_revision':previous['baseline_revision'],'before_revision':doc['current_revision'],
                  'after_revision':revision,'sides':state,'revision_kind':kind,'revision_label':label,
                  'last_reviewed':str(link['reviewed']),'link_provenance':link['provenance']}
                c.execute("INSERT INTO watched_notice(id,link_id,changed_revision,lang,kind,status,payload) VALUES (%s,%s,%s,%s,%s,'pending',%s)",
                  (uuid.uuid4().hex,link['id'],revision,lang,change_kind(previous['current_text'],current,valid),json.dumps(payload)))
                count+=1
            db.commit();return revision,count
        except Exception:db.rollback();raise

def review(notice_id,action,note):
    if action not in ('no_update','already_covered','needs_update','unlink'):raise ValueError('Choose a review outcome.')
    if not note.strip():raise ValueError('Add a short explanation so the review is auditable.')
    with connect() as db,db.cursor() as c:
        db.begin()
        try:
            # Lock order matches ingestion: link first, then notification.
            c.execute('SELECT link_id FROM watched_notice WHERE id=%s',(notice_id,));row=c.fetchone()
            if not row:raise ValueError('Unknown notification.')
            c.execute('SELECT * FROM watched_link WHERE id=%s FOR UPDATE',(row['link_id'],));link=c.fetchone()
            c.execute('SELECT * FROM watched_notice WHERE id=%s FOR UPDATE',(notice_id,));notice=c.fetchone()
            if notice['status'] not in ('pending','needs_update'):raise StaleRevision('This notification was already reviewed or replaced by a newer change.')
            state=json.loads(link['state'])
            if action in ('no_update','already_covered'):
                if not all(s['valid'] for s in state):raise ValueError('A passage link is uncertain. Repair or stop watching it first.')
                for side in state:side.update(baseline_text=side['current_text'],baseline_revision=side['current_revision'])
                c.execute('UPDATE watched_link SET state=%s,reviewed=CURRENT_TIMESTAMP WHERE id=%s',(json.dumps(state),link['id']))
            if action=='unlink':c.execute('UPDATE watched_link SET active=0 WHERE id=%s',(link['id'],))
            c.execute('UPDATE watched_notice SET status=%s,review_note=%s,reviewed=CURRENT_TIMESTAMP WHERE id=%s',
              (action,note[:4000],notice_id))
            c.execute('INSERT INTO watched_review VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)',(uuid.uuid4().hex,notice_id,action,note[:4000]))
            db.commit()
        except Exception:db.rollback();raise

def diff_html(before,after):
    old=re.findall(r'\s+|\S+',before);new=re.findall(r'\s+|\S+',after)
    pieces=[]
    for tag,a,b,x,y in difflib.SequenceMatcher(None,old,new,autojunk=False).get_opcodes():
        if tag in ('delete','replace'):pieces.extend([Markup('<del>'),escape(''.join(old[a:b])),Markup('</del>')])
        if tag in ('insert','replace'):pieces.extend([Markup('<ins>'),escape(''.join(new[x:y])),Markup('</ins>')])
        if tag=='equal':pieces.append(escape(''.join(new[x:y])))
    return Markup('').join(pieces)

def overview(topic=None):
    with connect() as db,db.cursor() as c:
        where=' WHERE l.topic=%s' if topic else '';args=(topic,) if topic else ()
        c.execute('''SELECT n.*,l.topic,l.title,l.note AS link_note FROM watched_notice n JOIN watched_link l ON l.id=n.link_id'''+where+' ORDER BY n.created DESC,n.id',args)
        notices=list(c.fetchall())
        c.execute('SELECT * FROM watched_link l'+where+' ORDER BY l.created DESC',args);links=list(c.fetchall())
    for n in notices:
        n['data']=json.loads(n['payload']);n['diff']=diff_html(n['data']['before'],n['data']['after'])
        n['counterparts']=[s for s in n['data']['sides'] if s['lang']!=n['lang']]
        n['check']=json.loads(n['check_result']) if n['check_result'] else None
    for l in links:l['sides']=json.loads(l['state'])
    return notices,links

def suggestions(topic,lang,quote):
    docs=ensure_topic(topic)
    if lang not in docs or not quote.strip() or docs[lang]['text'].count(quote)!=1:raise ValueError('Select an exact unique passage from the current source revision.')
    from pipeline import prepare_topic,PASSAGE_VERSION
    from prepare import embedding_model
    from core import MODEL,vector_bytes
    model=embedding_model();prepare_topic(topic,model)
    vector=vector_bytes(next(model.embed(['query: '+quote])))
    candidates=[]
    with connect() as db,db.cursor() as c:
        for target,doc in docs.items():
            if target==lang:continue
            c.execute('''SELECT id,text,heading,1-VEC_DISTANCE_COSINE(embedding,%s) AS similarity
              FROM review_passage WHERE topic=%s AND lang=%s AND version=%s
              ORDER BY VEC_DISTANCE_COSINE(embedding,%s)+0 LIMIT 3''',(vector,topic,target,PASSAGE_VERSION,vector))
            for row in c.fetchall():
                if doc['text'].count(row['text'])!=1:continue
                row.update(lang=target,revision=doc['current_revision'],title=doc['title']);candidates.append(row)
    return docs,candidates

def seed_demo():
    topic='Q2606233';docs=ensure_topic(topic)
    def sentence(lang,needle):
        return next(s.strip() for s in re.split(r'(?<=[.!?])\s+|\n',docs[lang]['text']) if needle in s)
    # Seed only once; never roll back a user's later edits or reviews.
    with connect() as db,db.cursor() as c:
        c.execute("SELECT id FROM watched_link WHERE topic=%s AND provenance='demo_baseline' LIMIT 1",(topic,));old=c.fetchone()
        if old:return old['id']
    source=sentence('en','In 1888 Swedish was made');target=sentence('fi','Vuonna 1888 koulut')
    link=create_link(topic,[{'lang':'en','quote':source},{'lang':'fi','quote':target}],
        'School instruction language in 1888','Demonstration baseline: the passages refer to Swedish-language schooling. No editor verification is claimed.','demo_baseline')
    ingest(topic,'en',docs['en']['text'].replace(source,source.replace('1888','1889'),1),docs['en']['current_revision'],
        label='Simulated date correction: 1888 → 1889 (not a real Wikipedia edit)')
    return link

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--seed-demo',action='store_true');parser.add_argument('--ingest-json');args=parser.parse_args();init()
    if args.seed_demo:print('Demo link:',seed_demo())
    if args.ingest_json:
        from pathlib import Path
        data=json.loads(Path(args.ingest_json).read_text(encoding='utf-8'))
        print(ingest(data['topic'],data['lang'],data['text'],data['base_revision'],kind='imported',
          label=data.get('label','Imported revision'),upstream_id=data.get('upstream_id')))
