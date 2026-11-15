"""Offline Argos/CTranslate2 translation, cached in MariaDB. No paid API calls."""
import argparse,hashlib,json,re,threading,zipfile
from functools import lru_cache
from pathlib import Path
import requests
from core import ROOT,connect

MODEL_VERSIONS={'fi':'1.9','sv':'1.5','ru':'1.9'}
MODEL_ROOT=ROOT/'model-cache'/'translation'
_lock=threading.Lock()

def init():
    with connect() as db,db.cursor() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS local_translation (
          id CHAR(64) PRIMARY KEY,lang CHAR(2),model VARCHAR(100),source MEDIUMTEXT,
          translated MEDIUMTEXT,created TIMESTAMP DEFAULT CURRENT_TIMESTAMP) CHARACTER SET utf8mb4''')

def install_models():
    MODEL_ROOT.mkdir(parents=True,exist_ok=True)
    index=requests.get('https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json',timeout=30)
    index.raise_for_status()
    for lang,version in MODEL_VERSIONS.items():
        dest=MODEL_ROOT/lang
        if list(dest.glob('**/model/model.bin')): print('Cached translation model',lang,flush=True);continue
        package=next(p for p in index.json() if p['from_code']==lang and p['to_code']=='en' and p['package_version']==version)
        url=next(u for u in package['links'] if u.startswith('https://argos-net.com/'))
        archive=MODEL_ROOT/(lang+'.argosmodel')
        print('Downloading local translation model',lang,flush=True)
        with requests.get(url,stream=True,timeout=(15,120)) as r:
            r.raise_for_status()
            with open(str(archive)+'.part','wb') as f:
                for chunk in r.iter_content(1024*1024):f.write(chunk)
        Path(str(archive)+'.part').replace(archive)
        dest.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            for member in z.infolist():
                target=(dest/member.filename).resolve()
                if not target.is_relative_to(dest.resolve()): raise ValueError('Unsafe model archive path.')
            z.extractall(dest)
        (dest/'provenance.json').write_text(json.dumps({'package':package,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
        print('Installed',lang,flush=True)

@lru_cache(maxsize=3)
def load_model(lang):
    import ctranslate2,sentencepiece
    folders=list((MODEL_ROOT/lang).glob('**/model/model.bin'))
    if not folders: raise RuntimeError('Local translation model not installed. Run local_translation.py --install.')
    root=folders[0].parent.parent
    if (root/'sentencepiece.model').exists():
        tokenizer=sentencepiece.SentencePieceProcessor(model_file=str(root/'sentencepiece.model'))
    else:
        from sacremoses import MosesTokenizer,MosesDetokenizer,MosesPunctNormalizer
        from subword_nmt.apply_bpe import BPE
        class BPETokenizer:
            def __init__(self):
                self.source=MosesTokenizer(lang);self.target=MosesDetokenizer('en');self.normalizer=MosesPunctNormalizer(lang)
                with open(root/'bpe.model',encoding='utf-8') as f:self.bpe=BPE(f)
            def encode(self,text,out_type=str):
                return self.bpe.process_line(' '.join(self.source.tokenize(self.normalizer.normalize(text)))).split()
            def decode(self,tokens):
                return self.target.detokenize(' '.join(tokens).replace('@@ ','').split())
        tokenizer=BPETokenizer()
    translator=ctranslate2.Translator(str(root/'model'),device='cpu',compute_type='int8',intra_threads=2)
    return tokenizer,translator

def cached_translation(text,lang):
    """Read the exact current model/text cache identity; never load a model."""
    if lang not in MODEL_VERSIONS:return None
    model=f'argos-{lang}-en-{MODEL_VERSIONS[lang]}-int8'
    identity=hashlib.sha256((model+'\0'+text).encode()).hexdigest()
    with connect() as db,db.cursor() as c:
        c.execute('SELECT translated FROM local_translation WHERE id=%s',(identity,));old=c.fetchone()
    return {'text':old['translated'],'model':model,'cached':True} if old else None


def translate(text,lang):
    if lang=='en':return {'text':text,'model':'original-English','cached':True}
    if lang not in MODEL_VERSIONS:raise ValueError('Only Finnish, Swedish and Russian to English are supported.')
    if not text.strip() or len(text)>16000:raise ValueError('Translation requires 1–16,000 characters.')
    model=f'argos-{lang}-en-{MODEL_VERSIONS[lang]}-int8'
    identity=hashlib.sha256((model+'\0'+text).encode()).hexdigest()
    with connect() as db,db.cursor() as c:
        c.execute('SELECT translated FROM local_translation WHERE id=%s',(identity,));old=c.fetchone()
    if old:return {'text':old['translated'],'model':model,'cached':True}
    # Keep CPU use bounded; split long sentences without silently truncating input.
    with _lock:
        # Another request may have filled this exact model/text while we waited.
        cached=cached_translation(text,lang)
        if cached:return cached
        tokenizer,translator=load_model(lang)
        segments=[]
        for sentence in re.split(r'(?<=[.!?])\s+|\n+',text):
            ids=tokenizer.encode(sentence,out_type=str)
            for start in range(0,len(ids),200):segments.append(ids[start:start+200])
        output=translator.translate_batch(segments,beam_size=2,max_batch_size=8,max_input_length=0,max_decoding_length=512)
        translated=' '.join(tokenizer.decode(o.hypotheses[0]) for o in output)
        with connect() as db,db.cursor() as c:
            c.execute('INSERT IGNORE INTO local_translation(id,lang,model,source,translated) VALUES (%s,%s,%s,%s,%s)',
              (identity,lang,model,text,translated))
    return {'text':translated,'model':model,'cached':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--install',action='store_true');args=p.parse_args();init()
    if args.install:install_models()
    else:
        for lang,text in [('fi','Vuonna 1888 koulut siirtyivät käyttämään kokonaan ruotsinkielistä opetusta.'),('sv','Tornedalingarna blev en nationell minoritet 1999.')]:
            print(lang,translate(text,lang),flush=True)
