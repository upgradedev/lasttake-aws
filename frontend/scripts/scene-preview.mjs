// The landing page shows the scene a judge is about to check before any run
// exists: its heading, how many beats the script requires, how many takes the
// production supplied, and the first lines of the lined script.
//
// Those numbers are the ones the whole entry leads with, and the rule for
// numbers here is that they come out of the same bytes the backend reads, never
// out of prose. So this is generated at build time from ../corpus, which is what
// the Lambda loads, and written into dist/ next to the built application. The
// page fetches it same-origin; there is no session and no API call behind it.
//
// Nothing in it is an assessment. Required beats and supplied takes are facts of
// the supplied records. Whether a beat is covered is only ever said by a
// checkpoint, and the page says so.
import {readFile,writeFile} from 'node:fs/promises';

const script=JSON.parse(await readFile('../corpus/script_revision.json','utf8'));
const takes=JSON.parse(await readFile('../corpus/takes.json','utf8'));

const beats=script.beats.filter(b=>b.required);
const preview={
  schema:'lasttake/scene-preview/v1',
  production_id:script.production_id,
  scene_id:script.scene_id,
  scene_heading:script.scene_heading,
  revision:script.revision,
  required_beats:beats.length,
  optional_beats:script.beats.length-beats.length,
  supplied_takes:takes.takes.length,
  // The first five required beats, page:line and slug only. Enough to show
  // that this is a lined script and not a form; not enough to pretend it is
  // the whole scene.
  opening_beats:beats.slice(0,5).map(b=>({beat_id:b.beat_id,page:b.page,line:b.line,slug:b.slug})),
  synthetic_notice:script.disclaimer,
};

if(!Number.isInteger(preview.required_beats) || preview.required_beats<1) throw new Error('scene preview: no required beats in the corpus');
if(!Number.isInteger(preview.supplied_takes) || preview.supplied_takes<1) throw new Error('scene preview: no takes in the corpus');
if(typeof preview.synthetic_notice!=='string' || !/fictional/i.test(preview.synthetic_notice)) throw new Error('scene preview: the corpus must say on its face that it is fictional');

await writeFile('dist/scene-preview.json',JSON.stringify(preview,null,2)+'\n');
console.log(`scene preview: ${preview.scene_id}, ${preview.required_beats} required beats, ${preview.supplied_takes} supplied takes`);
