/* Deliberately hand-authored UI fixtures, never stored as real engine findings. */
window.NeoWikiExamples = (() => {
  const e = (lang, quote, mark = '', translation = '') => ({lang, quote, mark, translation, illustrative: true});
  const winter = [
    ['causes', 'Why did the Winter War begin?', 'Causes of the war', ['en','fi','ru'],
      e('en','The war began after the Soviet Union invaded Finland. Negotiations over territorial demands had failed.','invaded Finland'),
      e('ru','Война началась после провала переговоров о территориальных требованиях и безопасности Ленинграда.','безопасности Ленинграда','The war began after negotiations over territorial demands and the security of Leningrad failed.'),
      'Compare how the accounts describe agency, security claims and the sequence of events. Shared context does not make every claim equivalent.',
      [['2012-01-01','omission'],['2015-06-01','framing'],['2019-02-01','contradiction'],['2022-04-01','framing'],['2024-01-01','contradiction']]],
    ['mainila','What happened at Mainila?','Events before the war',['en','fi','ru'],
      e('en','The shelling of Mainila was presented as a justification for military action. Responsibility for the incident requires careful sourcing.','Responsibility'),
      e('fi','Mainilan laukauksia käytettiin sodan perusteluna. Tapahtumien kulusta on esitetty erilaisia väitteitä.','erilaisia väitteitä','The Mainila shots were used to justify the war. Different claims have been made about the course of events.'),
      'Separate what a source reports was claimed at the time from what the article asserts happened.',
      [['2013-04-01','framing'],['2016-07-01','contradiction'],['2020-03-01','framing'],['2023-03-01','resolved']]],
    ['demands','How are the territorial demands explained?','Diplomatic negotiations',['en','fi','ru'],
      e('en','The negotiations included demands for territory on the Karelian Isthmus and a proposed exchange of land.','exchange of land'),
      e('ru','На переговорах обсуждались территориальные изменения на Карельском перешейке.','территориальные изменения','The negotiations discussed territorial changes on the Karelian Isthmus.'),
      'The second selected passage omits the proposed exchange. Check the full edition before calling this an article-wide omission.',
      [['2012-01-01','omission'],['2017-01-01','framing'],['2021-08-01','omission']]],
    ['outcome','How is the outcome described?','Outcome',['en','fi','ru'],
      e('en','Finland retained its independence but ceded territory under the peace treaty.','retained its independence'),
      e('fi','Rauhansopimuksessa Suomi luovutti alueita Neuvostoliitolle.','luovutti alueita','In the peace treaty Finland ceded territories to the Soviet Union.'),
      'The selected passages emphasize different consequences. Different emphasis alone does not establish a contradiction.',
      [['2014-03-01','omission'],['2018-05-01','framing'],['2022-09-01','resolved']]],
    ['losses','Which casualty estimates are compared?','Casualties',['en','fi','ru'],
      e('en','Casualty estimates vary between sources. Totals may include different categories of missing and wounded personnel.','different categories'),
      e('ru','Оценки потерь различаются в зависимости от источника и метода подсчёта.','метода подсчёта','Loss estimates differ depending on the source and counting method.'),
      'Reconcile date, source and counting method before comparing totals. These example excerpts do not themselves conflict.',
      [['2015-01-01','contradiction'],['2019-10-01','framing'],['2024-05-01','omission']]],
    ['support','What international support is mentioned?','International response',['en','fi'],
      e('en','Foreign volunteers and material support are discussed in the account of international responses.','Foreign volunteers'),
      e('fi','Ulkomailta saatiin materiaalista apua.','materiaalista apua','Material assistance was received from abroad.'),
      'Volunteer participation appears only in the selected English example. A full-article check is needed before proposing an addition.',
      [['2016-05-01','omission'],['2021-05-01','resolved']]],
    ['treaty','Which treaty terms receive emphasis?','Moscow Peace Treaty',['en','fi','ru'],
      e('en','The peace treaty required territorial concessions and affected the population living in the ceded areas.','affected the population'),
      e('ru','Мирный договор предусматривал территориальные уступки.','территориальные уступки','The peace treaty provided for territorial concessions.'),
      'The selected passages differ in whether they discuss civilian consequences. This is a coverage question.',
      [['2017-10-01','omission'],['2020-07-01','framing'],['2023-09-01','omission']]],
    ['evacuation','How is civilian displacement covered?','Civilian impact',['en','fi'],
      e('en','People living in the ceded territories were displaced following the settlement.','displaced'),
      e('fi','Luovutettujen alueiden asukkaita evakuoitiin.','evakuoitiin','Residents of the ceded territories were evacuated.'),
      'Check whether differences are due to translation, event scope or missing context. Neither sentence is evidence of editorial intent.',
      [['2019-01-01','omission'],['2022-01-01','framing']]]
  ];
  const torn = [
    ['recognition','Recognition: a decision in 1999 or effect in 2000?','Legal recognition',['en','sv','fi'],
      e('en','The community was recognized as a national minority in 2000.','2000'),
      e('sv','Gruppen erkändes som nationell minoritet genom ett beslut 1999.','1999','The group was recognized as a national minority through a decision in 1999.'),
      'A decision date and a law’s effective date can both be correct. Verify the legal milestones before changing a year.',
      [['2012-01-01','omission'],['2016-01-01','contradiction'],['2021-01-01','framing'],['2024-01-01','contradiction']]],
    ['identity','How is the community’s identity introduced?','Introduction',['en','fi','sv'],
      e('en','The community is introduced as an ethnic minority native to the region.','ethnic minority'),
      e('fi','Yhteisöä kuvataan alueen historiallisena alkuperäisväestönä.','alkuperäisväestönä','The community is described as the historical Indigenous population of the area.'),
      'Review terminology, geographic scope and sources with fluent editors. Identity framing is not automatically a factual conflict.',
      [['2013-01-01','framing'],['2020-01-01','omission'],['2022-01-01','framing']]],
    ['application','Is the application for Indigenous status included?','Recent developments',['en','fi'],
      e('en','This example excerpt discusses national-minority status.','national-minority'),
      e('fi','Esimerkkikatkelma käsittelee vuoden 2023 hakemusta alkuperäiskansa-asemasta.','2023','This example excerpt discusses a 2023 application for Indigenous status.'),
      'An application is different from granted recognition. Search the full counterpart article before proposing an addition.',
      [['2023-10-01','omission']]],
    ['education','How is the school-language policy described?','Language and education',['en','fi','sv'],
      e('en','The example discusses a shift to Swedish-language schooling.','schooling'),
      e('fi','Esimerkissä kuvataan siirtymistä ruotsinkieliseen opetukseen.','ruotsinkieliseen','The example describes a shift to Swedish-language teaching.'),
      'Comparable statements may align after scope and translation have been checked.',
      [['2012-01-01','omission'],['2017-01-01','framing'],['2020-01-01','resolved']]]
  ];
  const topics = [
    {id:'Q134949',title:'Winter War',description:'Conflict, causes and historical interpretation',languages:['en','fi','ru','sv'], aliases:['winter war','talvisota','зимняя война','war','finland','history'],kind:'Article', raw:winter},
    {id:'Q2606233',title:'Tornedalians',description:'Identity, language and minority recognition',languages:['en','fi','sv'], aliases:['tornedalians','tornedalingar','länsipohjalaiset','minority','recognition'],kind:'Article',raw:torn},
    {id:'group:recognition',title:'Minority recognition',description:'A sample semantic group · legal status, identity and recognition',languages:['en','fi','sv'],aliases:['minority recognition','national minority','indigenous status','legal recognition','identity'],kind:'Topic group',raw:torn}
  ];
  // An explicitly synthetic version history makes period stepping inspectable.
  // It must never be mistaken for quotations from actual Winter War revisions.
  const causeVersions = [
    [e('en','The example account describes failed negotiations followed by military action.','military action'),e('ru','В примере описываются переговоры, которые завершились без соглашения.','без соглашения','The example describes negotiations that ended without agreement.')],
    [e('en','This example emphasizes the invasion after negotiations failed.','the invasion'),e('ru','В этом примере главное внимание уделяется территориальным требованиям и безопасности.','безопасности','This example places the emphasis on territorial demands and security.')],
    [e('en','In this synthetic scenario, the negotiations ended before military action began.','before'),e('ru','В этом синтетическом примере те же переговоры продолжались после начала военных действий.','после','In this synthetic example, the same negotiations continued after military action began.')],
    [e('en','The revised example distinguishes the end of one negotiation round from later diplomatic contacts.','one negotiation round'),e('ru','В исправленном примере различаются переговорный раунд и более поздние дипломатические контакты.','более поздние','The revised example distinguishes a negotiation round from later diplomatic contacts.')],
    [e('en','In this synthetic revision, all diplomatic contacts had ended before military action began.','all diplomatic contacts'),e('ru','В этом синтетическом примере дипломатические контакты продолжались после начала военных действий.','продолжались после','In this synthetic example, diplomatic contacts continued after military action began.')]
  ];
  function dataset(topic) {
    const horizon='2025-08-01';
    return {topic,mode:'illustrative',asOf:horizon,warning:'Illustrative intervals and hand-authored example passages. These are not source quotations, assessed findings or verified historical boundaries.',
      rows:topic.raw.map(([id,title,section,languages,ours,theirs,reason,phases])=>({id,title,section,languages,grouped:true,
       phases:phases.map(([start,kind],i)=>({id:id+'-'+i,start,end:phases[i+1]?.[0]||horizon,kind,open:i===phases.length-1&&kind!=='resolved',
        reason:kind==='contradiction'?'This example period is labeled as a possible contradiction to demonstrate a stronger divergence state. The illustrative excerpts alone do not establish that judgment. '+reason:reason,
        action:'Verify the exact revisions, event scope and cited sources before proposing an edit.',
        evidence:id==='causes'?causeVersions[i]:[ours,theirs],illustrative:true}))}))};
  }
  return {topics,dataset};
})();
