'use strict';
const fields=['to','subject','body','version'];
function encodedSubject(subject){
 const chunks=[]; let word='';
 for(const char of subject){
  if(Buffer.byteLength(word+char)>42){chunks.push(word);word='';}
  word+=char;
 }
 chunks.push(word);
 return chunks.map(s=>'=?UTF-8?B?'+Buffer.from(s).toString('base64')+'?=').join('\r\n ');
}
function mime(draft,claimId){
 const lines=['To: '+draft.to,'Subject: '+encodedSubject(draft.subject),'Date: '+new Date().toUTCString(),
  'Message-ID: <'+claimId+'@citebase.local>','MIME-Version: 1.0','Content-Type: text/plain; charset=UTF-8',
  'Content-Transfer-Encoding: base64','',Buffer.from(draft.body.replace(/\r\n|\r|\n/g,'\r\n')).toString('base64').match(/.{1,76}/g).join('\r\n')];
 return Buffer.from(lines.join('\r\n')).toString('base64url');
}
async function dispatch(input,{work,send,save}){
 if(!input||Object.keys(input).some(k=>!['prospectId','confirm',...fields].includes(k))||
  input.confirm!==true||typeof input.prospectId!=='string'||!input.prospectId||input.prospectId.length>128||
  !/^[a-f0-9]{32}$/.test(input.version)||typeof input.to!=='string'||input.to.length>254||
  !/^[a-zA-Z0-9._%+'-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,63}$/.test(input.to)||
  typeof input.subject!=='string'||!input.subject||input.subject.length>500||/[\u0000-\u001f\u007f]/.test(input.subject)||
  typeof input.body!=='string'||!input.body||input.body.length>50000)throw Error('Invalid confirmation');
 const prepared=await work('outreach_prepare',{prospectId:input.prospectId,version:input.version});
 if(fields.some(k=>input[k]!==prepared[k]))throw Error('Draft changed');
 const claim=await work('outreach_claim',input);
 if(!/^[a-f0-9]{32}$/.test(claim.claimId)||fields.some(k=>claim[k]!==prepared[k]))throw Error('Invalid claim');
 let messageId;
 try{
  const reply=await send({raw:mime(prepared,claim.claimId)});
  if(typeof reply?.id!=='string'||!/^[A-Za-z0-9_-]{1,160}$/.test(reply.id))throw Error('Missing receipt');
  messageId=reply.id;
 }catch{return {status:'outcome_unknown',error:'Gmail delivery is unconfirmed. Check your Sent folder. This draft version is closed.'};}
 const receipt={provider:'gmail',prospectId:input.prospectId,version:input.version,claimId:claim.claimId,messageId,status:'provider_accepted'};
 try{await save(receipt);return {status:receipt.status,messageId,receiptSaved:true};}
 catch{return {status:receipt.status,messageId,receiptSaved:false};}
}
module.exports={dispatch};
