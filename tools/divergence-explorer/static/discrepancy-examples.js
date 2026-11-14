/* Topic metadata only. All graph/evidence data comes from the read-only API. */
window.NeoWikiExamples = {
  topics: [
    {id: 'Q134949', title: 'Winter War', kind: 'Wikipedia article',
      description: 'Historical comparisons in English, Finnish and Russian',
      aliases: ['winter war', 'talvisota', 'vinterkriget'], languages: ['en', 'fi', 'ru']},
    {id: 'Q2606233', title: 'Tornedalians', kind: 'Wikipedia article',
      description: 'Cached snapshot findings; historical lifetimes unknown',
      aliases: ['tornedalians', 'tornedalingar', 'länsipohjalaiset'], languages: ['en', 'fi', 'sv']}
  ],
  dataset: topic => ({topic, mode: 'unprepared', rows: [], asOf: '2025-07-16T10:12:37Z'})
};
