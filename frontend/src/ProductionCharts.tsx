import { useState } from 'react';
import type { Scene, RunState, EventRow } from './types';
import { words } from './model';

interface ProductionChartsProps {
  scene: Scene;
  state: RunState;
  events: EventRow[];
}

export function ProductionCharts({ scene, state, events }: ProductionChartsProps) {
  const [selectedBeat, setSelectedBeat] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [simulatedEvents, setSimulatedEvents] = useState<Array<{ id: string; type: string; time: string; note: string }>>([]);

  const requiredCount = state.counts?.required_beats ?? scene.required_beats ?? 10;
  const coveredCount = state.counts?.covered_with_evidence ?? 0;
  const exceptionCount = state.counts?.raising_exceptions ?? state.exceptions?.length ?? 0;
  const readinessPercent = requiredCount > 0 ? Math.round((coveredCount / requiredCount) * 100) : 0;

  // Gauge calculations (Circumference = 2 * PI * r = 2 * 3.14159 * 42 = 263.89)
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (readinessPercent / 100) * circumference;

  const handleSimulate = () => {
    if (simulating) return;
    setSimulating(true);
    const newSimEvent = {
      id: `evt-sim-${Date.now().toString().slice(-4)}`,
      type: 'take.ingested',
      time: new Date().toLocaleTimeString(),
      note: `Slate 42-B Take 3 synced · Sound Roll A04 · 35mm Arri Raw (Digest verified)`
    };
    setSimulatedEvents(prev => [newSimEvent, ...prev.slice(0, 4)]);
    setTimeout(() => {
      setSimulating(false);
    }, 1200);
  };

  return (
    <section
      className="panel"
      style={{
        margin: '24px 0',
        padding: '24px',
        background: 'linear-gradient(135deg, rgba(15, 23, 42, 0.95) 0%, rgba(13, 31, 45, 0.9) 100%)',
        border: '1px solid #1e3a5f',
        borderRadius: '12px',
        boxShadow: '0 8px 32px rgba(0, 0, 0, 0.37)'
      }}
      aria-label="Executive Production Analytics & Real-Time Telemetry"
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '20px' }}>
        <div>
          <span style={{ fontSize: '0.72rem', letterSpacing: '0.12em', color: 'var(--teal, #14b8a6)', fontWeight: 700, textTransform: 'uppercase' }}>
            ● ON-SET SCRIPT & COVERAGE TELEMETRY
          </span>
          <h2 style={{ fontSize: '1.35rem', margin: '4px 0 0', fontWeight: 700, color: '#f8fafc' }}>
            Production Wrap Readiness & Take Matrix
          </h2>
        </div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <span style={{ fontSize: '0.8rem', padding: '4px 10px', background: '#0f293d', color: '#38bdf8', borderRadius: '999px', border: '1px solid #0284c7' }}>
            Scene {scene.scene_id} · {scene.revision}
          </span>
          <button
            onClick={handleSimulate}
            disabled={simulating}
            style={{
              padding: '6px 14px',
              fontSize: '0.82rem',
              fontWeight: 600,
              background: simulating ? '#334155' : 'linear-gradient(135deg, #0284c7 0%, #0369a1 100%)',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              cursor: simulating ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            {simulating ? <span className="spinner" aria-hidden="true" style={{ width: '12px', height: '12px' }} /> : '▶'}
            {simulating ? 'Processing Ingest…' : 'Simulate Live Ingest Cycle'}
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: '20px' }}>
        {/* Radial Wrap Readiness Gauge */}
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.65)',
            border: '1px solid rgba(56, 189, 248, 0.2)',
            borderRadius: '10px',
            padding: '18px',
            display: 'flex',
            alignItems: 'center',
            gap: '20px'
          }}
        >
          <div style={{ position: 'relative', width: '110px', height: '110px', flexShrink: 0 }}>
            <svg width="110" height="110" viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
              <circle
                cx="50"
                cy="50"
                r={radius}
                fill="transparent"
                stroke="rgba(255, 255, 255, 0.1)"
                strokeWidth="8"
              />
              <circle
                cx="50"
                cy="50"
                r={radius}
                fill="transparent"
                stroke={readinessPercent > 80 ? '#14b8a6' : readinessPercent > 40 ? '#f59e0b' : '#ef4444'}
                strokeWidth="8"
                strokeDasharray={circumference}
                strokeDashoffset={strokeDashoffset}
                strokeLinecap="round"
                style={{ transition: 'stroke-dashoffset 0.6s ease-in-out' }}
              />
            </svg>
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center'
              }}
            >
              <span style={{ fontSize: '1.4rem', fontWeight: 800, color: '#f8fafc', lineHeight: 1 }}>
                {readinessPercent}%
              </span>
              <span style={{ fontSize: '0.65rem', color: '#94a3b8', textTransform: 'uppercase', marginTop: '2px' }}>
                Readiness
              </span>
            </div>
          </div>

          <div style={{ flex: 1 }}>
            <h4 style={{ margin: '0 0 6px', fontSize: '0.95rem', color: '#e2e8f0' }}>Pre-Wrap Clearance</h4>
            <p style={{ margin: '0 0 10px', fontSize: '0.8rem', color: '#94a3b8', lineHeight: 1.4 }}>
              {state.eligible
                ? 'All mandatory scene beats covered with verified camera reports and talent releases.'
                : `${exceptionCount} exception(s) require 1st AD / DIT human sign-off before wrap turnover.`}
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: 'rgba(20, 184, 166, 0.15)', color: '#14b8a6', borderRadius: '4px', border: '1px solid rgba(20, 184, 166, 0.3)' }}>
                {coveredCount}/{requiredCount} Beats Covered
              </span>
              <span style={{ fontSize: '0.75rem', padding: '2px 8px', background: exceptionCount > 0 ? 'rgba(239, 68, 68, 0.15)' : 'rgba(100, 116, 139, 0.2)', color: exceptionCount > 0 ? '#f87171' : '#94a3b8', borderRadius: '4px', border: '1px solid rgba(239, 68, 68, 0.3)' }}>
                {exceptionCount} Blockers
              </span>
            </div>
          </div>
        </div>

        {/* Real-time On-Set Telemetry Stream */}
        <div
          style={{
            background: 'rgba(15, 23, 42, 0.65)',
            border: '1px solid rgba(56, 189, 248, 0.2)',
            borderRadius: '10px',
            padding: '18px',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <h4 style={{ margin: 0, fontSize: '0.92rem', color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
              Live On-Set Event Stream
            </h4>
            <span style={{ fontSize: '0.72rem', color: '#64748b' }}>AWS EventBridge</span>
          </div>

          <div style={{ minHeight: '80px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {simulatedEvents.length > 0 && simulatedEvents.map(evt => (
              <div
                key={evt.id}
                style={{
                  padding: '6px 10px',
                  background: 'rgba(56, 189, 248, 0.15)',
                  borderLeft: '3px solid #38bdf8',
                  borderRadius: '4px',
                  fontSize: '0.78rem',
                  color: '#e2e8f0',
                  animation: 'fadeIn 0.3s ease-in'
                }}
              >
                <strong>{evt.time}</strong> · {evt.note}
              </div>
            ))}

            {events.slice(0, 3).map(event => (
              <div
                key={event.event_id}
                style={{
                  padding: '5px 8px',
                  background: 'rgba(255, 255, 255, 0.03)',
                  borderLeft: '3px solid #64748b',
                  borderRadius: '4px',
                  fontSize: '0.76rem',
                  color: '#94a3b8',
                  display: 'flex',
                  justifyContent: 'space-between'
                }}
              >
                <span>{words(event.event_type.replaceAll('.', ' '))}</span>
                <span style={{ color: '#64748b' }}>{new Date(event.occurred_at).toLocaleTimeString()}</span>
              </div>
            ))}

            {events.length === 0 && simulatedEvents.length === 0 && (
              <p style={{ margin: 'auto 0', fontSize: '0.78rem', color: '#64748b', fontStyle: 'italic' }}>
                No recent on-set events. Trigger simulation to stream live capture events.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Script Beat & Take Coverage Matrix */}
      <div style={{ marginTop: '20px' }}>
        <h4 style={{ margin: '0 0 10px', fontSize: '0.92rem', color: '#cbd5e1' }}>
          Script Beat Coverage Matrix
        </h4>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: '8px' }}>
          {scene.beats.map(beat => {
            const hasTake = beat.takes && beat.takes.length > 0;
            const hasPreferred = beat.takes?.some(t => t.preferred);
            const isSelected = selectedBeat === beat.beat_id;

            return (
              <button
                key={beat.beat_id}
                onClick={() => setSelectedBeat(isSelected ? null : beat.beat_id)}
                style={{
                  padding: '8px',
                  textAlign: 'left',
                  background: isSelected
                    ? 'rgba(56, 189, 248, 0.2)'
                    : hasTake
                    ? 'rgba(20, 184, 166, 0.1)'
                    : 'rgba(239, 68, 68, 0.1)',
                  border: isSelected
                    ? '1px solid #38bdf8'
                    : hasTake
                    ? '1px solid rgba(20, 184, 166, 0.3)'
                    : '1px solid rgba(239, 68, 68, 0.3)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  color: '#f8fafc'
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.72rem', fontWeight: 700, color: hasTake ? '#14b8a6' : '#f87171' }}>
                    {beat.beat_id}
                  </span>
                  {hasPreferred && <span style={{ fontSize: '0.72rem', color: '#f59e0b' }} title="Preferred Take Recorded">★</span>}
                </div>
                <div style={{ fontSize: '0.78rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '2px' }}>
                  {beat.slug}
                </div>
                <div style={{ fontSize: '0.68rem', color: '#94a3b8', marginTop: '4px' }}>
                  {hasTake ? `${beat.takes.length} take(s)` : 'Missing take'}
                </div>
              </button>
            );
          })}
        </div>

        {selectedBeat && (
          <div
            style={{
              marginTop: '12px',
              padding: '12px 16px',
              background: 'rgba(15, 23, 42, 0.9)',
              border: '1px solid #38bdf8',
              borderRadius: '8px',
              fontSize: '0.85rem'
            }}
          >
            {(() => {
              const b = scene.beats.find(x => x.beat_id === selectedBeat);
              if (!b) return null;
              return (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <strong>{b.beat_id}: {b.slug} (Script p.{b.page}:{b.line})</strong>
                    <button
                      onClick={() => setSelectedBeat(null)}
                      style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer' }}
                    >
                      ✕
                    </button>
                  </div>
                  <p style={{ margin: '4px 0 8px', color: '#cbd5e1' }}>{b.description}</p>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', fontSize: '0.78rem' }}>
                    <span>Characters: {b.characters.join(', ') || 'None'}</span>
                    <span>· Continuity Ref: {b.continuity_ref || 'None'}</span>
                    <span>· Planned Shot: {b.planned_shot || 'Standard coverage'}</span>
                  </div>
                </div>
              );
            })()}
          </div>
        )}
      </div>
    </section>
  );
}
