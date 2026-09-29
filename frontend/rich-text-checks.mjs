import assert from 'node:assert/strict';
import {fromDocument,toDocument} from './src/rich-text.ts';
const text={kind:'text',text:'Headline\nSmall bold italic',paragraphs:[
  {runs:[{text:'Headline',font:'Roboto,Regular',size:96,bold:true,underline:true}]},
  {runs:[{text:'Small ',size:24},{text:'bold',bold:true},{text:' italic',italic:true}]},
]};
assert.deepEqual(fromDocument(toDocument(text)),text);
assert.equal(fromDocument(toDocument({kind:'text',text:'Old label\nSecond line'})).text,'Old label\nSecond line');
assert.equal(fromDocument({type:'doc',content:[{type:'paragraph',content:[{type:'text',text:'A'},{type:'hardBreak'},{type:'text',text:'B'}]}]}).text,'A\nB');
assert.throws(()=>fromDocument({type:'doc',content:[{type:'script',text:'bad'}]}));
console.log('4 rich-text serialization checks passed');

const {starter, verticalAlignment} = await import('./src/api.ts');
const initial = starter({defaults:{sizeId:'29x90',font:'Roboto,Regular',fontSize:70,orientation:'standard',margin:24}});
assert.equal(initial.verticalAlign,'top');
assert.equal(verticalAlignment(initial),'top');
assert.equal(verticalAlignment({...initial,verticalAlign:undefined}),'center');
assert.equal(verticalAlignment({...initial,verticalAlign:undefined,content:text}),'top');
console.log('Initial and legacy vertical alignment checks passed');
