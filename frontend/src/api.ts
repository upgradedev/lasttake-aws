import type { Document } from './types';
export class ApiError extends Error {
  constructor(message:string,public readonly status:number){super(message);this.name='ApiError';}
}
export async function request<T>(path:string, body:Document = {}):Promise<T> {
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),35000);
  try {
  const response=await fetch(`/api/${path}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store',signal:controller.signal});
  let data: Document;
  try { data=await response.json() as Document; }
  catch { throw new Error('The service returned an unreadable response. Refresh saved state before retrying.'); }
  if(!response.ok) throw new ApiError(String(data.error ?? data.message ?? `Request failed (${response.status}).`),response.status);
  return data as T;
  } catch(error) {
    if(controller.signal.aborted)throw new Error('The request timed out. The server may have saved it. Refresh saved state before retrying a write.');
    throw error;
  } finally {clearTimeout(timer);}
}
export function errorMessage(error:unknown) { return error instanceof Error ? error.message : 'The service is unavailable. Refresh saved state before retrying.'; }
export function saveJson(name:string,data:unknown) {
  saveText(name,JSON.stringify(data,null,2),'application/json');
}
export function saveText(name:string,text:string,type='text/plain') {
  const url=URL.createObjectURL(new Blob([text],{type}));
  const anchor=document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click(); URL.revokeObjectURL(url);
}
