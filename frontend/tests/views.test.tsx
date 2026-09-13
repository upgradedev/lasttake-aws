import {describe,it,expect,vi} from 'vitest';
import {render,screen,fireEvent} from '@testing-library/react';
import {Landing} from '../src/Landing';
import {UserJourneysView} from '../src/UserJourneysView';
import {ArchitectureView} from '../src/ArchitectureView';
import {GtmProductionView} from '../src/GtmProductionView';
import {session} from './fixtures';

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
    fireEvent.click(screen.getByRole('button',{name:/STAGE 02/}));
    expect(screen.getByText(/Script Lined Beats & Coverage Reconciliation/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/STAGE 03/}));
    expect(screen.getByText(/10-Minute Pre-Wrap Alert & 1st AD Approval/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/STAGE 04/}));
    expect(screen.getByText(/Editorial Turnover & Immutable S3 Handoff/)).toBeVisible();
  });

  it('renders architecture view and switches layers',()=>{
    render(<ArchitectureView runId="run-123"/>);
    expect(screen.getByText('LastTake AWS Architecture')).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Reconciliation/}));
    expect(screen.getAllByText(/Lambda Fleet/)[0]).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Production Edge/}));
    expect(screen.getByText(/Strict Origin Access Control/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Serverless HTTP/}));
    expect(screen.getAllByText(/Amazon API Gateway v2/)[0]).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Strands Agentic/}));
    expect(screen.getByText(/AWS Strands SDK & Amazon Bedrock/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Operational Ledger/}));
    expect(screen.getByText(/Single-table design/)).toBeVisible();
    fireEvent.click(screen.getByRole('button',{name:/Editorial Turnover/}));
    expect(screen.getByText(/S3 Object Lock/)).toBeVisible();
  });

  it('renders production ROI view',()=>{
    render(<GtmProductionView runId="run-123"/>);
    expect(screen.getByText('Production ROI & Market Wedge')).toBeVisible();
    expect(screen.getByText('$50k – $250k')).toBeVisible();
    expect(screen.getByText('ScriptE Systems')).toBeVisible();
    expect(screen.getByText('What LastTake Replaces on the Production Cart')).toBeVisible();
  });
});
