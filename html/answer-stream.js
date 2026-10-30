'use strict';
async function readAnswerStream(response,onEvent){
 if(!response.body)throw Error('Streaming body unavailable');
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result=null;
 function line(text){if(!text.trim())return;const event=JSON.parse(text);if(event.type==='error'){const error=Error('Request failed');error.status=event.status;throw error;}if(event.type==='result')result=event.data;else onEvent(event);}
 try{while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});let index;while((index=buffer.indexOf('\n'))>=0){line(buffer.slice(0,index));buffer=buffer.slice(index+1);}if(done)break;}if(buffer.trim())line(buffer);if(!result)throw Error('Incomplete answer stream');return result;}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
}
if(typeof module!=='undefined')module.exports={readAnswerStream};
