/* Shared preview/native controls. Only an explicit click starts local translation. */
(function(){'use strict';
 window.PalimpsestIssueTranslations={mount(container,sources,request){
  container.replaceChildren();if(!sources?.length)return;
  for(const source of sources){const section=document.createElement('section'),label=document.createElement('p'),button=document.createElement('button'),output=document.createElement('p'),status=document.createElement('small');
   section.className='issue-translation';label.textContent='English translation · machine translated';button.type='button';output.lang='en';output.setAttribute('aria-live','polite');status.setAttribute('role','status');
   let text=source.text||'',pending=false;output.textContent=text;output.hidden=!text;button.textContent=text?'Hide English translation':'Translate '+source.lang.toUpperCase()+' into English';status.textContent=text?'Cached translation · may contain errors':'Runs on this server when requested; saved for future readers.';
   button.onclick=async()=>{if(pending)return;if(text){output.hidden=!output.hidden;button.textContent=output.hidden?'Show English translation':'Hide English translation';return;}pending=true;button.disabled=true;status.textContent='Translating this passage locally…';try{const data=await request(source.key);if(typeof data.text!=='string'||!data.text.trim())throw Error('The local translator returned no text.');text=data.text;source.text=text;output.textContent=text;output.hidden=false;button.textContent='Hide English translation';status.textContent=(data.cached?'Loaded from cache':'Translated locally and cached')+' · may contain errors';}catch(error){status.textContent=error.message||'Translation unavailable. Retry to translate this exact passage.';button.textContent='Retry English translation';}finally{pending=false;button.disabled=false;}};
   section.append(label,button,output,status);container.append(section);
  }
 },mountInline(container,sources,request){for(const slot of container.querySelectorAll('.issue-translation-slot')){const source=(sources||[]).find(item=>item.key===slot.dataset.translationKey);if(source)this.mount(slot,[source],request);}}};
}());
