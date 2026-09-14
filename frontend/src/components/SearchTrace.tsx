import { useEffect, useState } from 'react'
import type { SearchProgress } from '../types'

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
        {events.map((event) => (
          <li key={`${event.request_id}-${event.sequence}`}>
            <time>{(event.elapsed_ms / 1000).toFixed(1)}초</time>
            <span>{event.message}</span>
            {event.embedding_input !== undefined ? (
              <div className="trace-embedding">
                <strong>임베딩 API 입력 검색어</strong>
                <pre tabIndex={0} aria-label="임베딩 입력 검색어"><code>{event.embedding_input}</code></pre>
                <small>Deployment: {event.deployment}</small>
              </div>
            ) : null}
            {event.sql ? (
              <details className="trace-query">
                <summary>SQL 및 바인딩 값</summary>
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