import type {Document} from './types';

export const EVIDENCE_FILE_LIMIT=64*1024;
export function parseEvidenceDocument(text:string):Document {
  const value:unknown=JSON.parse(text);
  if(!value || typeof value!=='object' || Array.isArray(value))throw new Error('Use one JSON record object, without a run or session envelope.');
  return value as Document;
}
export async function readEvidenceFile(file:File) {
  if(!file.name.toLowerCase().endsWith('.json'))throw new Error('Choose a .json record file. PDFs, images, CSV and media are not supported.');
  if(file.size>EVIDENCE_FILE_LIMIT)throw new Error('Choose a JSON record no larger than 64 KiB. Nothing was uploaded.');
  return file.text();
}
