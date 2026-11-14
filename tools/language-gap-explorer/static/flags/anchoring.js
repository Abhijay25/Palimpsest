/* Lightweight standalone adaptation of the native Palimpsest anchor resolver. */
(function(root){
 'use strict';
 function cells(table,side){return [...table.querySelectorAll('[data-diff-side="'+side+'"].mw-diff-inline-'+(side==='old'?'deleted':'added'))];}
 function resolve(table,flags){
  const anchored=[],unanchored=[];
  for(const flag of flags){
   const quote=String(flag.anchor_text||'').trim();let found=null;
   for(const cell of cells(table,flag.side==='old'?'old':'new'))if(quote&&cell.textContent.includes(quote)){found=cell;break;}
   if(!found){unanchored.push(flag);continue;}
   const index=found.textContent.indexOf(quote),walker=document.createTreeWalker(found,NodeFilter.SHOW_TEXT),nodes=[];
   while(walker.nextNode())nodes.push(walker.currentNode);
   let cursor=0,marks=[];
   for(const node of nodes){
    const start=cursor,end=cursor+node.nodeValue.length;cursor=end;
    if(index>=end||index+quote.length<=start)continue;
    const a=Math.max(index,start)-start,b=Math.min(index+quote.length,end)-start;
    const after=node.splitText(b),selected=node.splitText(a),mark=document.createElement('mark');
    mark.className='diff-anchor';mark.dataset.flagId=flag.id;
    selected.parentNode.replaceChild(mark,selected);mark.append(selected);marks.push(mark);void after;
   }
   if(marks.length)anchored.push({flag,marks,mark:marks[0]});else unanchored.push(flag);
  }
  return {anchored,unanchored};
 }
 function unwrap(table){table.querySelectorAll('mark.diff-anchor').forEach(mark=>mark.replaceWith(...mark.childNodes));}
 root.PalimpsestFlagsAnchoring={resolve,unwrap};
})(window);
