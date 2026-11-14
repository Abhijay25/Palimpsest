"""Hand-authored AI response fixture. Quotes come from real snapshot text.

No API is called, and no category or explanation is a model conclusion.
The same interface can later be implemented by a reviewed AI provider.
"""
import re

CATEGORIES = {
    'conflict': 'Possible conflict', 'coverage': 'Extra coverage',
    'framing': 'Different framing', 'same': 'Same information',
    'uncertain': 'Needs context',
}

def evidence(articles,lang,needle,translation,highlight):
    article=articles.get(lang)
    if not article or needle not in article['text']: return None
    # Pick an exact sentence from the immutable snapshot, never a generated quote.
    sentences=re.split(r'(?<=[.!?])\s+|\n',article['text'])
    quote=next(s.strip() for s in sentences if needle in s)
    start=article['text'].find(quote)
    before=article['text'][:start]
    headings=re.findall(r'^#{1,6}\s+(.+)$',before,re.M)
    return dict(lang=lang,title=article['title'],quote=quote,translation=translation,
        highlight=highlight if highlight in quote else '',section=headings[-1] if headings else 'Introduction',
        rev_id=article['rev_id'],start=start,end=start+len(quote),
        url=f'https://{lang}.wikipedia.org/w/index.php?oldid={article["rev_id"]}')

def mock_review(topic,articles):
    if topic!='Q2606233': return []
    definitions=[
      dict(id='recognition-date',category='conflict',title='Recognition date: 1999 or 2000?',
        summary='English and Swedish use different years for national-minority recognition.',
        reasoning='Both excerpts concern recognition of the same group. The Swedish sentence describes a parliamentary decision in 1999; the English sentence gives 2000. These may refer to different legislative milestones rather than an incorrect date.',
        action='Check the parliamentary decision and the law’s effective date. If both dates are valid, name the milestone explicitly in each article.',
        note='Clarify whether 1999 refers to parliamentary adoption and 2000 to the law taking effect. Cite the primary legislation before changing either date.',
        evidence=[('en','recognized as a national minority in Sweden in 2000',None,'2000'),
                  ('sv','officiellt erkända nationella minoriteter 1999','Tornedalians became one of Sweden’s officially recognized national minorities in 1999, when parliament adopted the government’s National Minorities in Sweden proposal and thereby ratified the Council of Europe framework convention.','1999')]),
      dict(id='indigenous-application',category='coverage',title='A 2023 application adds a distinct legal milestone',
        summary='Finnish mentions an application for Indigenous status; English describes national-minority recognition.',
        reasoning='An application for Indigenous status is different from recognition as a national minority. The selected English evidence does not cover the application. This is a candidate coverage gap, not proof that the event is missing everywhere in the article.',
        action='Search the full English article for the application, then locate a suitable source before proposing an addition. Preserve the distinction between the two statuses.',
        note='Investigate the October 2023 application for Indigenous status mentioned in the Finnish edition. Add it only if it is absent, relevant and supported by a reliable source.',
        evidence=[('fi','Vuoden 2023 lokakuussa','In October 2023, Tornedalians submitted an application to Sweden’s Minister for Culture and Rural Affairs seeking Indigenous status.','2023'),
                  ('en','recognized as a national minority in Sweden in 2000',None,'national minority')]),
      dict(id='identity-framing',category='framing',title='The introductions frame identity differently',
        summary='Finnish describes a Finnish Indigenous population; English introduces an ethnic minority.',
        reasoning='The passages refer to the same community but emphasize different identities and geographic scope. The wording alone does not establish a factual contradiction. Translation choices and each edition’s sources need review.',
        action='Compare the cited sources and terminology with editors fluent in both languages. Explain distinctions rather than automatically copying one introduction into the other.',
        note='Discuss the lead’s terminology: the Finnish and English introductions emphasize different aspects of identity. Verify how each source defines the community and its geographic scope.',
        evidence=[('fi','ovat historiallisesti Länsipohjassa asuva suomalainen alkuperäisväestö','Länsipohjalaiset (also Tornedalians, with several local names) are the Finnish Indigenous population historically living in Länsipohja.','suomalainen alkuperäisväestö'),
                  ('en','are an ethnic minority native',None,'ethnic minority')]),
      dict(id='school-language',category='same',title='Both editions describe the 1888 school-language change',
        summary='Different wording, but the school-language claim aligns.',
        reasoning='Both selected sentences say schooling shifted to Swedish in 1888. The English excerpt also discusses civil life, which the Finnish sentence does not address. The overlap is equivalent; the extra clause is not a contradiction.',
        action='No correction is suggested for the shared school-language claim. Check the extra civil-life detail separately if expanding coverage.',
        note='The two excerpts agree on Swedish-language schooling in 1888. No edit is proposed for that shared claim.',
        evidence=[('en','In 1888 Swedish was made',None,'1888'),
                  ('fi','Vuonna 1888 koulut','In 1888, schools switched to teaching entirely in Swedish.','1888')]),
    ]
    findings=[]
    for definition in definitions:
        entries=[evidence(articles,*item) for item in definition.pop('evidence')]
        if any(e is None for e in entries): continue
        definition['evidence']=entries
        definition['label']=CATEGORIES[definition['category']]
        definition['mode']='mock'
        findings.append(definition)
    return findings
