const {test}=require('node:test');const assert=require('node:assert/strict');
const {readAnswerStream}=require('../html/answer-stream.js');
test('split UTF-8 packets retain text and final answer',async()=>{
 const text='{"type":"answer_delta","text":"한국어 日本語 中文"}\n{"type":"result","data":{"answer":"done"}}\n';
 const bytes=new TextEncoder().encode(text),events=[];
 const response=new Response(new ReadableStream({start(c){for(let i=0;i<bytes.length;i+=2)c.enqueue(bytes.slice(i,i+2));c.close();}}));
 assert.equal((await readAnswerStream(response,e=>events.push(e))).answer,'done');
 assert.equal(events[0].text,'한국어 日本語 中文');
});
test('truncated stream is not a completed answer',async()=>{
 await assert.rejects(readAnswerStream(new Response('{"type":"answer_delta","text":"partial"}\n'),()=>{}),/Incomplete/);
});
