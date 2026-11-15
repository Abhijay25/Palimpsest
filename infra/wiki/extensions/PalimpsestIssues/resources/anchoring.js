/* Lightweight standalone adaptation of the native Palimpsest anchor resolver. */
(function(root){
 'use strict';
 function cells(table,side){return [...table.querySelectorAll('[data-diff-side="'+side+'"].mw-diff-inline-'+(side==='old'?'deleted':'added'))];}
 function sourceNodes(cell){const walker=document.createTreeWalker(cell,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode()){const node=walker.currentNode;if(!node.parentElement?.closest('.issue-translation-slot,.flag-inline-pin'))nodes.push(node);}return nodes;}
 function resolve(table,flags){
  const anchored=[],unanchored=[];
  for(const flag of flags){
   const quote=String(flag.anchor_text||'').trim();let found=null;
   for(const cell of cells(table,flag.side==='old'?'old':'new'))if(quote&&sourceNodes(cell).map(n=>n.nodeValue).join('').includes(quote)){found=cell;break;}
   if(!found){unanchored.push(flag);continue;}
   const nodes=sourceNodes(found),text=nodes.map(n=>n.nodeValue).join('');let index=text.indexOf(quote);
   if(text.lastIndexOf(quote)!==index){const context=String(flag.context_sentence||'');const begin=context?text.indexOf(context):-1;if(begin<0||text.lastIndexOf(context)!==begin||!context.includes(quote)){unanchored.push(flag);continue;}index=begin+context.indexOf(quote);}
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
