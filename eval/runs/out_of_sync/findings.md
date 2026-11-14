# OUT_OF_SYNC scout verification

- swaps: deterministic 5, semantic 0
- controls: deterministic 0, semantic 0
- failed revision fetches: 0
- semantic judge: enabled

## Findings

- swaps | Kastelholman linna | rev 23612683 | deterministic | 1634 -> 6767 | section: Merkityksen väheneminen ja rappeutuminen | page still says: Jälleenrakennettu linna menetti kuitenkin pian merkityksensä, kun vuonna 1634 Ahvenanmaa liitettiin lääniuudistuksessa Turun lääniin.
- swaps | Punakaarti | rev 2836120 | deterministic | 1906 -> 1916 | section: Punakaartien synty | page still says: Radikalisoitumisen vuoksi elokuussa 1906 lakkautettiin Helsingin punakaarti, jonka päällikkönä toimi Suomen armeijasta 1800-luvun lopulla eronnut kapteeni Johan Kock.
- swaps | Tarja Halonen | rev 527332 | deterministic | 11 -> 15 | section: Introduction | page still says: joulukuuta 1943 Helsinki) on Suomen 11.
- swaps | Jämsänkoski | rev 14376553 | deterministic | 2009 -> 2010 | section: Introduction | page still says: 2009
- swaps | Laatokka | rev 14495623 | deterministic | 18 -> 14 | section: Rantakaupungit | page still says: 18

## Against the judge (g08_scout_base, v8 + highlights, no reviewer)

| page (real reverted swap) | judge alone | out of sync |
|---|---|---|
| Kastelholman linna 1634 -> 6767 | admin | deterministic hit |
| Punakaarti 1906 -> 1916 | review | deterministic hit (page still says "elokuussa 1906 ... punakaarti") |
| Tarja Halonen 11 -> 15 | review | deterministic hit (page still says "Suomen 11. presidentti") |
| Jämsänkoski 2009 -> 2010 | none | deterministic hit (table value) |
| Laatokka 18 -> 14 | review | deterministic hit (table value) |

5/25 real swaps, 0/25 controls; complementary to the judge: 1 new catch and 3 review->admin with the page's own contradicting sentence as evidence. Display gap: table/infobox hits quote a bare value ("2009", "18"); the card should show the row/parameter label.
