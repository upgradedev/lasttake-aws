import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent} from '@testing-library/react';
import {Landing} from '../src/Landing';
import {UserJourneysView} from '../src/UserJourneysView';
import {ArchitectureView} from '../src/ArchitectureView';
import {GtmProductionView} from '../src/GtmProductionView';
import {WrapBoard} from '../src/WrapBoard';
import {scene,state,session} from './fixtures';

describe('documentation and showcase views',()=>{
  it('renders landing page with actions and preview',()=>{
    const start=vi.fn();
    render(<Landing session={session} busy={false} page="overview" start={start}/>);
    expect(screen.getByRole('heading',{name:'Know what still blocks wrap.'})).toBeVisible();
    expect(screen.getByRole('button',{name:'Start this fictional shoot day'})).toBeVisible();
    expect(screen.getByRole('button',{name:'New shoot-day run'})).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:'Start this fictional shoot day'}));
    expect(start).toHaveBeenCalled();
  });
  it('renders user journeys view and switches stages',()=>{
    render(<UserJourneysView runId="run-123"/>);
    expect(screen.getByText('The 4 Production Assurance Journeys')).toBeVisible();
    expect(screen.getByText('Camera & Sound Log Ingest')).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/STAGE 01/}));
    expect(screen.getByText(/On a fast-paced set/)).toBeVisible();
  });
  it('renders architecture view and switches layers',()=>{
    render(<ArchitectureView runId="run-123"/>);
    expect(screen.getByText('LastTake AWS Architecture')).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Reconciliation/}));
    expect(screen.getByText(/Lambda Fleet/)).toBeVisible();
  });
  it('renders production ROI view',()=>{
    render(<GtmProductionView runId="run-123"/>);
    expect(screen.getByText('Production ROI & Market Wedge')).toBeVisible();
    expect(screen.getByText('$50k – $250k')).toBeVisible();
    expect(screen.getByText('ScriptE Systems')).toBeVisible();
  });
  it('renders wrap board with counts and verdicts',()=>{
    render(<WrapBoard state={state} scene={scene}/>);
    expect(screen.getByTestId('wrap-board')).toBeVisible();
    expect(screen.getByText('Covered with evidence')).toBeVisible();
  });
});
