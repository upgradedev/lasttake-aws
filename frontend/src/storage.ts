const memory=new Map<string,string>();
let unavailable=false;
export function readPreference(key:string) {
  try {return localStorage.getItem(key) ?? memory.get(key) ?? null;}
  catch {unavailable=true;return memory.get(key) ?? null;}
}
export function writePreference(key:string,value:string) {
  memory.set(key,value);
  try {localStorage.setItem(key,value);}catch{unavailable=true;}
}
export function storageNotice() {
  return unavailable ? 'Browser storage is unavailable. You can use this tab, but reloading may start a separate session. Saved records remain on the server.' : '';
}
