import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {describe,expect,it,vi} from 'vitest';
import {App} from '../src/App';
import {Intake} from '../src/Intake';
import {scene,session,state} from './fixtures';

function liveApi(current:()=>typeof state) {
  return vi.fn(async(url:string,init:RequestInit)=>{
    if(url==='/api/session')return {ok:true,status:200,json:async()=>session};
    if(url==='/api/scene')return {ok:true,status:200,json:async()=>scene};
    if(url==='/api/events')return {ok:true,status:200,json:async()=>({events:[]})};
    const body=JSON.parse(init.body as string);
    return {ok:true,status:200,json:async()=>({...current(),run_id:body.run_id})};
  });
}

describe('disconnect and authoritative reconnect',()=>{
  it('labels the last confirmed snapshot read-only and forces review when the server revision changed',async()=>{
    let current=state;const fetcher=liveApi(()=>current);vi.stubGlobal('fetch',fetcher);
    localStorage.setItem('lasttake.session',session.session_id);location.hash=`#scene?run=${state.run_id}&finding=${state.exceptions[0].finding_id}`;
    const user=userEvent.setup();render(<App/>);
    expect(await screen.findByTestId('connectivity-status')).toHaveTextContent('Connected');
    expect(screen.getByTestId('connectivity-status').querySelector('time')).toHaveAttribute('dateTime',expect.stringMatching(/^\d{4}-\d\d-\d\dT/));
    const decision=await screen.findByRole('button',{name:'Record decision'});

    act(()=>window.dispatchEvent(new Event('offline')));
    await waitFor(()=>expect(screen.getByTestId('connectivity-status')).toHaveTextContent('Offline'));
    expect(screen.getByTestId('connectivity-status')).toHaveTextContent('Saved snapshot · read-only');
    expect(decision).toBeDisabled();
    await user.click(decision);
    expect(fetcher.mock.calls.filter(([url])=>url==='/api/decide')).toHaveLength(0);

    current={...state,package_revision_digest:'authoritative-new-digest'};
    act(()=>window.dispatchEvent(new Event('online')));
    expect(await screen.findByRole('heading',{name:'Saved evidence changed since your last confirmed view'})).toBeVisible();
    expect(screen.getByTestId('connectivity-status')).toHaveTextContent('Connected');
    expect(screen.getByRole('button',{name:'Record decision'})).toBeDisabled();
    await user.click(screen.getByRole('button',{name:'I reviewed the current saved revision'}));
    await waitFor(()=>expect(screen.getByRole('button',{name:'Record decision'})).toBeEnabled());
    expect(fetcher.mock.calls.filter(([url])=>url==='/api/decide')).toHaveLength(0);
  });

  it('marks a lost mutation response unknown and reconnects with reads but no replay',async()=>{
    const fetcher=liveApi(()=>state);vi.stubGlobal('fetch',fetcher);
    localStorage.setItem('lasttake.session',session.session_id);location.hash=`#scene?run=${state.run_id}&finding=${state.exceptions[0].finding_id}`;
    const user=userEvent.setup();render(<App/>);
    await screen.findByRole('button',{name:'Record decision'});
    await user.type(screen.getByLabelText('Your name in this demo'),'Sam');
    await user.type(screen.getByLabelText('Reason for this exact evidence'),'Continuity is intentional.');
    fetcher.mockRejectedValueOnce(new Error('Connection dropped after send'));
    await user.click(screen.getByRole('button',{name:'Record decision'}));
    expect(await screen.findByTestId('connectivity-status')).toHaveTextContent('request outcome is unknown. It has not been replayed');
    expect(fetcher.mock.calls.filter(([url])=>url==='/api/decide')).toHaveLength(1);

    act(()=>window.dispatchEvent(new Event('online')));
    expect(await screen.findByText('Saved state re-read from the server. The decide request was not replayed.')).toBeVisible();
    await waitFor(()=>expect(screen.getByTestId('connectivity-status')).toHaveTextContent('Connected'));
    expect(fetcher.mock.calls.filter(([url])=>url==='/api/decide')).toHaveLength(1);
  });
});

describe('tab-scoped evidence drafts',()=>{
  it('restores only the exact session/run draft and clears it after confirmed save',async()=>{
    const submit=vi.fn().mockResolvedValue(true);const close=vi.fn();const user=userEvent.setup();
    const first=render(<Intake scene={scene} busy={false} guided={false} sessionId={session.session_id} runId={state.run_id} revisionDigest={state.package_revision_digest} onSubmit={submit} onClose={close}/>);
    await user.click(screen.getByLabelText('Advanced JSON entry'));
    fireEvent.change(screen.getByLabelText('Document JSON'),{target:{value:'{"take_id":"T-DRAFT"}'}});
    expect(screen.getByText(/Unsent draft kept in this tab/)).toBeVisible();
    first.unmount();

    const wrong=render(<Intake scene={scene} busy={false} guided={false} sessionId={session.session_id} runId="another-run" revisionDigest={state.package_revision_digest} onSubmit={submit} onClose={close}/>);
    expect(screen.queryByLabelText('Document JSON')).toBeNull();
    expect(screen.queryByText(/Unsent draft kept in this tab/)).toBeNull();
    wrong.unmount();

    const restored=render(<Intake scene={scene} busy={false} guided={false} sessionId={session.session_id} runId={state.run_id} revisionDigest={state.package_revision_digest} onSubmit={submit} onClose={close}/>);
    expect(screen.getByLabelText('Document JSON')).toHaveValue('{"take_id":"T-DRAFT"}');
    await user.click(screen.getByRole('button',{name:'Save evidence & rerun checks'}));
    expect(submit).toHaveBeenCalledWith('take',{take_id:'T-DRAFT'});
    restored.unmount();

    render(<Intake scene={scene} busy={false} guided={false} sessionId={session.session_id} runId={state.run_id} revisionDigest={state.package_revision_digest} onSubmit={submit} onClose={close}/>);
    expect(screen.queryByLabelText('Document JSON')).toBeNull();
    expect(screen.queryByText(/Unsent draft kept in this tab/)).toBeNull();
  });
});
