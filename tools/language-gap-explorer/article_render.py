"""Render untrusted corpus Markdown without raw HTML or embedded remote images."""
from html import escape
from urllib.parse import urljoin
from markdown_it import MarkdownIt
from markupsafe import Markup

def render_article(text,lang,title):
    md=MarkdownIt('commonmark',{'html':False}).enable('table')
    tokens=md.parse(text)
    # FineWiki can repeat the article title as its first heading.
    if len(tokens)>2 and tokens[0].type=='heading_open' and tokens[1].content.strip().casefold()==title.casefold():
        tokens=tokens[3:]
    contents=[]
    for i,token in enumerate(tokens):
        if token.type=='heading_open':
            anchor='section-'+str(len(contents)+1)
            token.attrSet('id',anchor)
            contents.append({'id':anchor,'title':tokens[i+1].content,'level':token.tag})
        for child in token.children or []:
            if child.type=='link_open':
                child.attrSet('href',urljoin(f'https://{lang}.wikipedia.org/',child.attrGet('href') or ''))
                child.attrSet('rel','noopener')
    # Keep the source's captions as text; don't load uncached external image URLs.
    md.add_render_rule('image',lambda self,tokens,idx,options,env: '<span class="image-caption">'+escape(tokens[idx].content)+'</span>')
    return Markup(md.renderer.render(tokens,md.options,{})),contents
