import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent,within} from '@testing-library/react';
import {Landing} from '../src/Landing';
import {ArchitectureView} from '../src/ArchitectureView';
import {ProductionCharts} from '../src/ProductionCharts';
import {WrapBoard} from '../src/WrapBoard';
import {session,scene,state} from './fixtures';

// These views are read by judges more than by supervisors, which is exactly why
// they must not say anything the deployed system does not do. Each test here
// pins both what the view shows and what it must never show.

describe('landing',()=>{
  it('answers audience, problem, result and first action, with one primary action',()=>{
    const start=vi.fn();
    render(<Landing session={{...session,runs:[]}} busy={false} page="overview" start={start}/>);
    expect(screen.getByRole('heading',{name:'Know what still blocks wrap.'})).toBeVisible();
    expect(screen.getByText(/For the script supervisor and 1st AD:/)).toBeVisible();
    expect(screen.getByRole('region',{name:'Start a shoot-day review'})).toHaveTextContent('saved editorial turnover');
    const start_button=screen.getByRole('button',{name:'Start this fictional shoot day'});
    expect(start_button).toHaveClass('primary');
    expect(screen.queryByRole('button',{name:'New shoot-day run'})).toBeNull();
    expect(screen.queryByRole('link',{name:/Continue my saved shoot day/})).toBeNull();
    fireEvent.click(start_button);
    expect(start).toHaveBeenCalledOnce();
  });
  it('offers a returning person their saved shoot day by status and date, never a silent jump',()=>{
    render(<Landing session={session} busy={false} page="scene" start={vi.fn()}/>);
    const cont=screen.getByRole('link',{name:'Continue my saved shoot day'});
    expect(cont).toHaveAttribute('href',`#scene?run=${session.runs[0].run_id}`);
    expect(cont).toHaveClass('primary');
    expect(screen.getByText(/Checkpoint saved, decisions open/)).toBeVisible();
    expect(screen.getByRole('button',{name:'Start this fictional shoot day'})).not.toHaveClass('primary');
  });
  it('states no benefit figure, no competitor and no clearance',()=>{
    render(<Landing session={session} busy={false} page="overview" start={vi.fn()}/>);
    const text=document.body.textContent ?? '';
    for(const banned of ['$','ROI','Scriptation','ScriptE','WORM','DynamoDB','Bedrock (Claude','guarantee','clear to shoot','legally cleared','< 5 Seconds'])expect(text).not.toContain(banned);
    expect(text).not.toContain('fifteen minutes');
    expect(text).not.toContain('a pickup day');
    expect(text).toContain('has not measured time saved, avoided pickups or production cost');
    expect(text).toContain('Bedrock is not active in this browser');
    expect(text).toContain('absent evidence is a finding, never a pass');
  });
});

describe('architecture',()=>{
  it('names only the deployed tiers and their limits, and embeds the repository diagram',()=>{
    render(<ArchitectureView runId="run-123"/>);
    expect(screen.getByRole('heading',{level:1,name:'Architecture'})).toBeVisible();
    expect(screen.getByRole('img',{name:/React workspace served from S3 through CloudFront/})).toHaveAttribute('src','/architecture.svg');
    for(const tier of ['Amazon S3 + Amazon CloudFront','Amazon API Gateway (HTTP API)','AWS Lambda (arm64) running the Strands Agents SDK','Amazon Aurora DSQL','Amazon EventBridge'])expect(screen.getByText(tier)).toBeVisible();
    const text=document.body.textContent ?? '';
    expect(text).toContain('offline lexical reader');
    expect(text).toContain('not active here');
    for(const banned of ['DynamoDB','Object Lock','WORM','Claude 3.5','guarantee','bulletproof','$'])expect(text).not.toContain(banned);
    expect(text).toContain('no Merkle proof');
    expect(screen.getByRole('link',{name:'Back to wrap status'})).toHaveAttribute('href','#overview?run=run-123');
  });
});

describe('beat matrix',()=>{
  it('shows every required beat as not assessed before a checkpoint, even with takes on file',()=>{
    render(<ProductionCharts scene={scene} state={{...state,counts:null,beats:[]}}/>);
    expect(screen.getByText(/required beats, not assessed yet/)).toBeVisible();
    const cells=screen.getAllByRole('button',{pressed:false});
    expect(cells).toHaveLength(scene.beats.filter(b=>b.required).length);
    for(const cell of cells)expect(cell).toHaveAttribute('data-status','not_assessed');
    expect(screen.queryByText(/Simulate/)).toBeNull();
    expect(screen.queryByText(/Telemetry/i)).toBeNull();
  });
  it('colours a cell only by the checkpoint outcome and explains the selected beat from real records',()=>{
    render(<ProductionCharts scene={scene} state={state}/>);
    expect(screen.getByText('1 of 2 required beats have evidence behind them')).toBeVisible();
    const covered=screen.getByRole('button',{name:/B-01/});
    expect(covered).toHaveAttribute('data-status','covered_with_evidence');
    const uncovered=screen.getByRole('button',{name:/B-17/});
    expect(uncovered).toHaveAttribute('data-status','not_assessed');
    fireEvent.click(covered);
    const detail=screen.getByRole('status');
    expect(within(detail).getByText(/B-01 · page 41, line 3/)).toBeVisible();
    expect(detail).toHaveTextContent('1 supplied take: slate 42A/1');
    expect(detail).toHaveTextContent('Checkpoint: covered, basis corroborated by the interpreter');
    fireEvent.click(covered);
    expect(screen.queryByRole('status')).toBeNull();
  });
});

describe('wrap board',()=>{
  it('reads every tile from the assessment and never shows a zero before one exists',()=>{
    const {rerender}=render(<WrapBoard scene={scene} state={{...state,counts:null}}/>);
    const board=screen.getByTestId('wrap-board');
    expect(board).toHaveTextContent('Required beats2');
    expect(within(board).getAllByText('Not assessed')).toHaveLength(4);
    rerender(<WrapBoard scene={scene} state={state}/>);
    expect(board).toHaveTextContent('Covered with evidence1');
    expect(board).toHaveTextContent('Raising exceptions1');
    expect(board).toHaveTextContent('No release record0');
    expect(board).toHaveTextContent('Evidence gateBlocked');
    expect(board).toHaveTextContent('Human wrap decisionNot approved');
    rerender(<WrapBoard scene={scene} state={{...state,eligible:true,wrap_approved:true,turnover:{}}}/>);
    expect(board).toHaveTextContent('Evidence gateEligible');
    expect(board).toHaveTextContent('Approved by the 1st AD');
    expect(board).not.toHaveTextContent('Recorded by the 1st AD');
    expect(board).toHaveTextContent('TurnoverSaved');
  });
  it('sets a tile that carries a status instead of a number in the pending style',()=>{
    const pending=()=>Array.from(screen.getByTestId('wrap-board').querySelectorAll('.tile-pending'),tile=>tile.querySelector('span')?.textContent);
    const {rerender}=render(<WrapBoard scene={scene} state={{...state,counts:null}}/>);
    expect(pending()).toEqual(['Covered with evidence','Raising exceptions','No release record']);
    rerender(<WrapBoard scene={scene} state={state}/>);
    expect(pending()).toEqual([]);
    expect(screen.getByTestId('wrap-board').querySelectorAll('.tile')).toHaveLength(4);
    rerender(<WrapBoard scene={scene} state={{...state,counts:{...state.counts!,raising_exceptions:null}}}/>);
    expect(pending()).toEqual(['Raising exceptions']);
    expect(screen.getByTestId('wrap-board')).toHaveTextContent('Raising exceptionsUnknown');
  });
});
