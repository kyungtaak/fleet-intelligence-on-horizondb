import { lazy, Suspense, useEffect, useId, useRef, useState } from 'react'
import type { CSSProperties, PointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { AlignLeft, Braces, Check, Copy, FileCode2, GripVertical, Maximize2, Network, WrapText, X } from 'lucide-react'
import type { QueryPlanNode, SearchProgress } from '../types'

const SqlViewer = lazy(() => import('./SqlViewer').then(module => ({ default: module.SqlViewer })))

interface PlanNodeProps {
  node: QueryPlanNode
  selected: QueryPlanNode | null
  onSelect: (node: QueryPlanNode) => void
}

function PlanNode({ node, selected, onSelect }: PlanNodeProps) {
  return (
    <li className="plan-branch">
      <button type="button" className={`plan-node${node['Index Name'] ? ' plan-node-index' : ''}`}
        aria-pressed={selected === node} onClick={() => onSelect(node)}>
        <strong>{node['Node Type']}</strong>
        {node['Index Name'] ? <code>{node['Index Name']}</code> : null}
        {node['Relation Name'] ? <code>{node['Relation Name']}</code> : null}
        <span className="plan-node-estimates">
          <span>예상 행 <b>{node['Plan Rows'] ?? '-'}</b></span>
          <span>비용 <b>{node['Startup Cost'] ?? '-'} ~ {node['Total Cost'] ?? '-'}</b></span>
        </span>
      </button>
      {node.Plans?.length ? <ul>{node.Plans.map((child, index) => <PlanNode key={index} node={child} selected={selected} onSelect={onSelect} />)}</ul> : null}
    </li>
  )
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const title = state === 'copied' ? '복사 완료' : state === 'failed' ? '복사 실패' : label
  return (
    <button type="button" className="icon-button" title={title} aria-label={title} onClick={async () => {
      try {
        await navigator.clipboard.writeText(text)
        setState('copied')
      } catch {
        setState('failed')
      }
    }}>
      {state === 'copied' ? <Check size={16} /> : <Copy size={16} />}
    </button>
  )
}

interface QueryPlanProps {
  plan: QueryPlanNode
  query: SearchProgress | undefined
}

function QueryPlanDialog({ plan, query, onClose }: QueryPlanProps & { onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  const sqlPanelId = useId()
  const columnsRef = useRef<HTMLDivElement>(null)
  const [view, setView] = useState<'nodes' | 'json'>('nodes')
  const [selectedNode, setSelectedNode] = useState<QueryPlanNode | null>(null)
  const [sqlShare, setSqlShare] = useState(60)
  const [stacked, setStacked] = useState(() => window.matchMedia('(max-width: 760px)').matches)
  const [formatted, setFormatted] = useState(true)
  const [wrap, setWrap] = useState(true)
  const text = JSON.stringify(plan, null, 2)
  const sql = query?.sql?.trim()
  const parameters = query?.parameters === undefined ? null : JSON.stringify(query.parameters, null, 2)

  useEffect(() => {
    const media = window.matchMedia('(max-width: 760px)')
    const change = () => setStacked(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])

  function resize(event: PointerEvent<HTMLDivElement>) {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
    const bounds = columnsRef.current?.getBoundingClientRect()
    if (!bounds) return
    const offset = stacked ? event.clientY - bounds.top : event.clientX - bounds.left
    const size = stacked ? bounds.height : bounds.width
    setSqlShare(Math.max(30, Math.min(75, Math.round((offset - 5) / (size - 10) * 100))))
  }

  useEffect(() => {
    const dialog = dialogRef.current
    const trigger = document.activeElement
    dialog?.showModal()
    return () => {
      dialog?.close()
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus()
    }
  }, [])

  return createPortal(
    <dialog ref={dialogRef} className="query-plan-dialog" aria-labelledby={titleId} aria-describedby={descriptionId}
      onCancel={event => { event.preventDefault(); onClose() }}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onClose()
        }
      }}
      onClick={event => {
        if (event.target !== event.currentTarget) return
        const bounds = event.currentTarget.getBoundingClientRect()
        if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose()
      }}>
      <header className="query-plan-heading">
        <Network size={24} aria-hidden="true" />
        <div>
          <h2 id={titleId}>예상 실행 계획</h2>
          <p id={descriptionId}>EXPLAIN (FORMAT JSON) · 실제 실행 시간 미수집</p>
        </div>
        <button type="button" className="icon-button" aria-label="실행 계획 닫기" title="닫기 (Esc)" onClick={onClose}><X size={18} /></button>
      </header>
      <div ref={columnsRef} className="query-plan-columns" style={{ '--sql-share': `${sqlShare}fr`, '--plan-share': `${100 - sqlShare}fr` } as CSSProperties}>
        <section id={sqlPanelId} className="query-plan-sql" aria-label="조회 SQL 및 바인딩 값">
          <header className="query-plan-section-heading">
            <h3>SQL</h3>
            {sql ? <div className="plan-toolbar" role="group" aria-label="SQL 표시 방식">
              <button type="button" className="icon-button" title="정돈된 SQL" aria-label="정돈된 SQL" aria-pressed={formatted} onClick={() => setFormatted(true)}><AlignLeft size={16} /></button>
              <button type="button" className="icon-button" title="원본 SQL" aria-label="원본 SQL" aria-pressed={!formatted} onClick={() => setFormatted(false)}><FileCode2 size={16} /></button>
              <button type="button" className="icon-button" title="자동 줄바꿈" aria-label="자동 줄바꿈" aria-pressed={wrap} onClick={() => setWrap(current => !current)}><WrapText size={16} /></button>
              <CopyButton text={sql} label="원본 SQL 복사" />
            </div> : null}
          </header>
          <div className="query-plan-sql-content">
            {sql ? <Suspense fallback={<><div className="sql-plan-match" role="status">SQL viewer 로딩 중</div><div /></>}>
              <SqlViewer source={sql} selectedNode={selectedNode} formatted={formatted} wrap={wrap} />
            </Suspense> : <><div /><p>수집된 SQL이 없습니다.</p></>}
            <details className="query-plan-bindings">
              <summary>바인딩 값 · %s 순서</summary>
              {parameters !== null ? <>
                <CopyButton text={parameters} label="바인딩 값 복사" />
                <pre tabIndex={0} aria-label="조회 바인딩 값"><code>{parameters}</code></pre>
              </> : <p>수집된 바인딩 값이 없습니다.</p>}
            </details>
          </div>
        </section>
        <div className="query-plan-splitter" role="separator" tabIndex={0} aria-label="SQL과 EXPLAIN 크기 조절"
          aria-controls={sqlPanelId} aria-orientation={stacked ? 'horizontal' : 'vertical'}
          aria-valuemin={30} aria-valuemax={75} aria-valuenow={sqlShare} aria-valuetext={`SQL ${sqlShare}%, EXPLAIN ${100 - sqlShare}%`}
          title="분할 크기 조절 (두 번 클릭: 6:4)"
          onDoubleClick={() => setSqlShare(60)}
          onPointerDown={event => { event.preventDefault(); event.currentTarget.focus(); event.currentTarget.setPointerCapture(event.pointerId) }}
          onPointerMove={resize}
          onPointerUp={event => { if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }}
          onKeyDown={event => {
            const increase = stacked ? 'ArrowDown' : 'ArrowRight'
            const decrease = stacked ? 'ArrowUp' : 'ArrowLeft'
            if (![increase, decrease, 'Home', 'End'].includes(event.key)) return
            event.preventDefault()
            setSqlShare(current => event.key === 'Home' ? 30 : event.key === 'End' ? 75 : Math.max(30, Math.min(75, current + (event.key === increase ? 2 : -2))))
          }}><GripVertical size={14} aria-hidden="true" /></div>
        <section className="query-plan-output" aria-label="실행 계획 그래프 및 JSON">
          <header className="query-plan-section-heading">
            <h3>EXPLAIN</h3>
            <div className="plan-toolbar" role="group" aria-label="실행 계획 표시 방식">
              <button className="icon-button" type="button" title="그래프 보기" aria-label="그래프 보기" aria-pressed={view === 'nodes'} onClick={() => setView('nodes')}><Network size={16} /></button>
              <button className="icon-button" type="button" title="JSON 보기" aria-label="JSON 보기" aria-pressed={view === 'json'} onClick={() => setView('json')}><Braces size={16} /></button>
              <CopyButton text={text} label="실행 계획 JSON 복사" />
            </div>
          </header>
          <div className="query-plan-output-content">
            {view === 'nodes' ? <ul className="plan-tree" aria-label="실행 계획 노드"><PlanNode node={plan} selected={selectedNode} onSelect={setSelectedNode} /></ul>
              : <pre tabIndex={0} aria-label="예상 실행 계획 JSON"><code>{text}</code></pre>}
          </div>
        </section>
      </div>
    </dialog>,
    document.body,
  )
}

function QueryPlan({ plan, query }: QueryPlanProps) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" className="query-plan-open" aria-haspopup="dialog" onClick={() => setOpen(true)}>
        <Network size={15} aria-hidden="true" />실행 계획 보기<Maximize2 size={13} aria-hidden="true" />
      </button>
      {open ? <QueryPlanDialog plan={plan} query={query} onClose={() => setOpen(false)} /> : null}
    </>
  )
}

interface SearchTraceProps {
  events: SearchProgress[]
  outcome: 'running' | 'completed' | 'failed' | 'cancelled'
  startedAt: number
  durationMs?: number
}

const OUTCOMES = {
  running: '처리 중', completed: '완료', failed: '실패', cancelled: '중단',
}

export function SearchTrace({ events, outcome, startedAt, durationMs }: SearchTraceProps) {
  const [now, setNow] = useState(startedAt)
  useEffect(() => {
    if (outcome !== 'running') return
    const timer = window.setInterval(() => setNow(performance.now()), 250)
    return () => window.clearInterval(timer)
  }, [outcome])
  const elapsed = durationMs ?? Math.max(0, now - startedAt)
  return (
    <details className="search-trace" open={outcome === 'running'}>
      <summary>실행 내역 · {OUTCOMES[outcome]} · {(elapsed / 1000).toFixed(1)}초</summary>
      <ol>
        {events.map((event, index) => (
          <li key={`${event.request_id}-${event.sequence}`}>
            <time>{(event.elapsed_ms / 1000).toFixed(1)}초</time>
            <span>{event.message}</span>
            {event.embedding_input !== undefined ? (
              <div className="trace-embedding">
                <strong>임베딩 입력 검색어</strong>
                <pre tabIndex={0} aria-label="임베딩 입력 검색어"><code>{event.embedding_input}</code></pre>
                <small>Deployment: {event.deployment}</small>
              </div>
            ) : null}
            {event.sql ? (
              <details className="trace-query">
                <summary>SQL 및 바인딩 값</summary>
                <CopyButton text={event.sql.trim()} label="SQL 복사" />
                <pre tabIndex={0} aria-label="실행 SQL"><code>{event.sql.trim()}</code></pre>
                <strong>매개변수 (SQL의 %s 순서)</strong>
                <pre tabIndex={0} aria-label="SQL 매개변수"><code>{JSON.stringify(event.parameters, null, 2)}</code></pre>
              </details>
            ) : null}
            {event.filters ? (
              <details className="trace-query">
                <summary>적용 조건</summary>
                <pre tabIndex={0}><code>{JSON.stringify(event.filters, null, 2)}</code></pre>
              </details>
            ) : null}
            {event.plan ? <QueryPlan plan={event.plan} query={events.slice(0, index).reverse().find(previous =>
              previous.request_id === event.request_id && previous.stage === 'db_query' && previous.sql,
            )} /> : null}
            {event.provider ? <small>{event.provider === 'horizondb' ? 'HorizonDB' : 'Azure OpenAI 직접 호출'}{event.model_alias ? ` · ${event.model_alias}` : ''}{event.duration_ms !== undefined ? ` · ${event.duration_ms}ms` : ''}</small> : null}
            {event.reference_date ? <small>날짜 기준: {event.reference_date} · {event.timezone}</small> : null}
            {event.dimensions !== undefined ? <small>{event.dimensions}차원</small> : null}
            {event.fetched_count !== undefined ? (
              <small>DB 수신 {event.fetched_count}행 · {event.duration_ms}ms (추가 결과 확인용 행 포함 가능)</small>
            ) : null}
            {event.returned_count !== undefined ? (
              <small>화면 전달 {event.returned_count}건{event.has_more ? ' · 추가 결과 있음' : ''}</small>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  )
}