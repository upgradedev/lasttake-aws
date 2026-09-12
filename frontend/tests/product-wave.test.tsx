import {it,expect,vi} from 'vitest';
import {fireEvent,render,screen,within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {WorkflowNext,wrapHeadline} from '../src/WorkflowNext';
import {ApprovalConsole} from '../src/Actions';
import {Turnover} from '../src/Turnover';
import {link} from '../src/model';
import {scene,state,finding} from './fixtures';

it('never promotes absent, changed or unreadable evidence to a current wrap decision',()=>{
  expect(wrapHeadline({...state,counts:null,eligible:true})).toBe('Wrap has not been assessed');
  expect(wrapHeadline({...state,needs_checkpoint:true})).toContain('fresh checkpoint');
  expect(wrapHeadline(state)).toContain('blocked');
  const eligible={...state,pending_approval:null,eligible:true};
  expect(wrapHeadline(eligible)).toBe('Eligible for a human wrap decision');
  expect(wrapHeadline({...eligible,wrap_approved:true})).toBe('Human wrap approval recorded');
  expect(wrapHeadline({...eligible,wrap_approved:true},true)).toBe('Refresh before deciding');
  expect(wrapHeadline({...eligible,pending_approval:{id:'wrap-current',evidence_changed:true,reason:{kind:'wrap',required_role:'first_ad',note:'Review'}}})).toContain('out of date');
});

it('connects actual source observation, blocking reason, owner and exact finding link',()=>{
  render(<WorkflowNext state={{...state,causes:[...state.causes,...state.causes]}} scene={scene} detailed/>);
  const brief=screen.getByTestId('workflow-next');
  expect(within(brief).getByText(finding.observation)).toBeVisible();
  expect(brief).toHaveTextContent('Blocks wrap: Not reviewed');
  expect(brief).toHaveTextContent('Script supervisor: Write the intent down.');
  expect(within(brief).getAllByRole('listitem')).toHaveLength(1);
  expect(within(brief).getByRole('link',{name:scene.locations['CR-01']})).toHaveAttribute('href',link('scene',state.run_id,undefined,{finding:finding.finding_id}));
  expect(brief).toHaveTextContent('Human wrap decisionNot approved');
  expect(brief).toHaveTextContent('Editorial turnoverNot published');
});

it('retains unlinked causes and directs users to all causes without inventing a source',()=>{
  const causes=Array.from({length:5},(_,i)=>({finding_id:null,requirement_id:'missing-'+i,reason:'Missing source '+i,required_role:'dit' as const}));
  const {rerender}=render(<WorkflowNext state={{...state,causes}} detailed/>);
  expect(screen.getAllByRole('listitem')).toHaveLength(3);
  expect(screen.getByRole('link',{name:'Review all 5 blocking causes'})).toHaveAttribute('href',link('scene',state.run_id,undefined,{filter:'approval'}));
  expect(screen.getByRole('link',{name:'missing-0'})).toHaveAttribute('href',link('scene',state.run_id,undefined,{filter:'approval'}));
  expect(screen.getByText('Missing source 0')).toBeVisible();
  rerender(<WorkflowNext state={{...state,causes:[]}} detailed/>);
  expect(screen.getByText(/No blocking explanation/)).toBeVisible();
  expect(screen.getByTestId('decision-headline')).toHaveTextContent('blocked');
});

it('shows the safe recovery for an unassessed, stale or historical returning run',()=>{
  const props={...state,pending_approval:null};
  const {rerender}=render(<WorkflowNext state={{...props,counts:null}} detailed/>);
  expect(screen.getByText(/Start the checkpoint to find/)).toBeVisible();
  rerender(<WorkflowNext state={{...props,needs_checkpoint:true}} detailed/>);
  expect(screen.getByText('Checkpoint required')).toBeVisible();
  const published={...props,eligible:true,wrap_approved:true,turnover:{package_revision_digest:state.package_revision_digest}};
  rerender(<WorkflowNext state={published} detailed/>);
  expect(screen.getByText('Saved for current evidence')).toBeVisible();
  rerender(<WorkflowNext state={published} requiresRefresh detailed/>);
  expect(screen.getByText('Saved record; currency unknown')).toBeVisible();
  expect(screen.queryByText('Saved for current evidence')).toBeNull();
  expect(screen.getByText(/saved view may be out of date/)).toBeVisible();
  rerender(<WorkflowNext state={{...published,package_revision_digest:'changed'}} detailed/>);
  expect(screen.getByText('Historical; do not use for changed evidence')).toBeVisible();
  expect(screen.getByText(/Start a new shoot-day run for a new turnover/)).toBeVisible();
});

it('explains the exact pending wrap consequence and keeps the original role and stale guards',async()=>{
  const user=userEvent.setup(),act=vi.fn().mockResolvedValue(true);
  const pending={id:'exact-wrap-request',reason:{kind:'wrap' as const,required_role:'first_ad' as const,note:'Current evidence only'}};
  const current={...state,eligible:true,pending_approval:pending};
  const {rerender}=render(<ApprovalConsole state={current} role="first_ad" busy={false} act={act}/>);
  const scope=screen.getByTestId('wrap-decision-scope');
  expect(scope).toHaveTextContent(scene.scene_id);expect(scope).toHaveTextContent(scene.revision);
  expect(scope).toHaveTextContent('does not publish it');expect(scope).toHaveTextContent('Declining leaves wrap unapproved');
  await user.click(screen.getByRole('button',{name:'Approve wrap'}));
  expect(act).toHaveBeenCalledWith('wrap',{interrupt_id:'exact-wrap-request',approve:true,role:'first_ad'});
  rerender(<ApprovalConsole state={{...current,pending_approval:{...pending,evidence_changed:true}}} role="first_ad" busy={false} act={act}/>);
  expect(screen.getByRole('button',{name:'Approve wrap'})).toBeDisabled();
  await user.click(screen.getByRole('button',{name:'Decline wrap'}));
  expect(act).toHaveBeenLastCalledWith('wrap',{interrupt_id:'exact-wrap-request',approve:false,role:'first_ad'});
  rerender(<ApprovalConsole state={current} role="editorial" busy={false} act={act}/>);
  expect(screen.queryByRole('button',{name:'Approve wrap'})).toBeNull();
});

const manifest={package_revision_digest:state.package_revision_digest,scene_id:scene.scene_id,script_revision:scene.revision,generated_at:'2026-09-12T12:00:00Z',wrap_approved_by:{actor:'Synthetic AD',role:'first_ad'},outstanding_and_accepted_exceptions:[{finding_id:'retained',requirement_id:'T-013',required_role:'dit',observation:'Camera identity disagrees.',recommended_action:'Compare the original camera report.'}],beat_to_take_map:[{beat_id:'B-17',slug:'Reaction',takes:[{take_id:'T-900',slate:'42L/1',media_id:'MEDIA-LATE',timecode_in:'10:00:00:00'}]},{beat_id:'B-18',slug:'Insert',takes:[]},{beat_id:'B-19',takes:[]},{beat_id:'B-20',takes:[]}]};
it('editorial can read retained work and search the saved map without opening raw JSON',async()=>{
  const user=userEvent.setup();
  render(<Turnover state={{...state,eligible:true,wrap_approved:true,turnover:manifest}} busy={false} publish={vi.fn()}/>);
  expect(screen.getByTestId('editorial-decision')).toHaveTextContent('Synthetic AD · 1st AD');
  expect(screen.getByRole('region',{name:'Retained exceptions for editorial'})).toHaveTextContent('Compare the original camera report.');
  expect(screen.getByRole('status')).toHaveTextContent('4 of 4 beat entries match. Showing the first 3');
  const search=screen.getByRole('searchbox',{name:'Find beat or take in turnover'});
  await user.type(search,'media-late');
  expect(search).toHaveFocus();expect(screen.getByRole('table')).toHaveTextContent('B-17 · Reaction');
  expect(screen.getByRole('status')).toHaveTextContent('1 of 4');
  await user.clear(search);await user.type(search,'missing record');
  expect(screen.getByText('No saved beat or take matches this search.')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Clear turnover search'}));
  expect(search).toHaveValue('');expect(screen.getByRole('table')).toHaveTextContent('No supplied take');
  expect(screen.getByText('Inspect saved manifest').closest('details')).not.toHaveAttribute('open');
});

it('missing manifest fields remain unknown and historical records remain inspectable',()=>{
  const {rerender}=render(<Turnover state={{...state,turnover:{}}} busy={false} publish={vi.fn()}/>);
  expect(screen.getByText(/No exception entries were supplied/)).toBeVisible();
  expect(screen.getByText(/No beat-to-take map was supplied/)).toBeVisible();
  expect(screen.getByTestId('editorial-decision')).toHaveTextContent('Unknown · Unknown');
  rerender(<Turnover state={{...state,eligible:true,wrap_approved:true,package_revision_digest:'new-evidence',turnover:manifest}} busy={false} publish={vi.fn()}/>);
  expect(screen.getByTestId('editorial-decision')).toHaveTextContent('Historical record');
  expect(screen.getByText(/Evidence has changed since this turnover/)).toBeVisible();
  expect(screen.getByRole('button',{name:'Download turnover'})).toBeEnabled();
  fireEvent.click(screen.getByText('Source fingerprints'));
  expect(screen.getByText(state.package_revision_digest)).toBeVisible();
});
