const {test}=require('node:test');
const assert=require('node:assert/strict');
const {dispatch}=require('../../site/api/_lib/google-mail');
const draft={prospectId:'fixture',version:'a'.repeat(32),to:'editor@example.test',subject:'Citation',body:'A fixture only.',confirm:true};
function fixture(uncertain=false){
 let claimed=false,sends=0;
 return {get sends(){return sends;},async work(op){if(claimed)throw Error('Claimed');if(op==='outreach_prepare')return draft;claimed=true;return {...draft,claimId:'b'.repeat(32)};},async send(){sends++;if(uncertain)throw Error();return {id:'abc'};},async save(){}};
}
for(const uncertain of [false,true])test('one provider call across repeat, uncertain='+uncertain,async()=>{
 const f=fixture(uncertain), r=await dispatch(draft,f);
 assert.equal(r.status,uncertain?'outcome_unknown':'provider_accepted');
 await assert.rejects(dispatch(draft,f));assert.equal(f.sends,1);
});
test('tampering and missing confirmation prevent all delivery',async()=>{
 for(const patch of [{to:'x@example.test'},{subject:'Hi\r\nBcc: victim@example.test'},{confirm:false},{raw:'x'}]){
  const f=fixture();await assert.rejects(dispatch({...draft,...patch},f));assert.equal(f.sends,0);
 }
});
