import { useEffect, useEffectEvent, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  ArrowRight,
  Bot,
  LocateFixed,
  RotateCcw,
  Send,
  Square,
  UserRound,
} from 'lucide-react'
import type { SearchProgress, SearchResponse, Shipment, ShipmentStatus } from '../types'
import { StatusBadge } from './StatusBadge'
import { SearchTrace } from './SearchTrace'

const SUGGESTIONS = [
  '지연된 배송을 찾아주세요',
  '아시아에서 출발한 의료용품을 찾아주세요',
  '부산 반경 100km 이내에서 출발한 배송을 찾아주세요',
  '2026년 9월 1일부터 30일까지 도착 예정인 지연 배송을 찾아주세요',
  '싱가포르 반경 5,000km 안의 반도체 관련 배송을 의미 유사도와 현재 위치 거리로 함께 정렬해 주세요',
  '목적지에 가장 가까운 배송 2개를 찾아주세요',
]

const SEARCH_MODE_LABELS: Record<SearchResponse['search_mode'], string> = {
  sql: 'SQL 조건 검색',
  gis: 'PostGIS 공간 검색',
  diskann_cosine: '의미 검색',
  hybrid: '조건 + 의미 검색',
  not_searched: '조건 확인 필요',
}

const STATUS_LABELS_KO: Record<ShipmentStatus, string> = {
  in_transit: '운송 중',
  delivered: '배송 완료',
  delayed: '지연',
  exception: '문제 발생',
  unknown: '상태 미확인',
}

interface ChatMessage {
  id: number
  role: 'assistant' | 'user'
  text: string
  shipments?: Shipment[]
  chatModel?: string
  chatProvider?: SearchResponse['chat_provider']
  searchMode?: SearchResponse['search_mode']
  hasMore?: boolean
  filters?: SearchResponse['applied_filters']
  trace?: SearchProgress[]
  outcome?: 'completed' | 'failed' | 'cancelled'
  startedAt?: number
  durationMs?: number
}

interface ChatPanelProps {
  externalBusy: boolean
  onSearch: (query: string, onProgress: (event: SearchProgress) => void, signal: AbortSignal) => Promise<SearchResponse>
  selectedNumber: string | null
  onSelect: (shipment: Shipment) => void
  onLocate: (shipment: Shipment) => void
  onShowAll: () => void
  queryRequest: { id: number; query: string } | null
}

const initialMessage: ChatMessage = {
  id: 1,
  role: 'assistant',
  text: '안녕하세요. 어떤 배송을 확인해 드릴까요?',
}

export function ChatPanel({ onSearch, externalBusy, selectedNumber, onSelect, onLocate, onShowAll, queryRequest }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([initialMessage])
  const [input, setInput] = useState('')
  const [searching, setSearching] = useState(false)
  const messageEnd = useRef<HTMLDivElement>(null)
  const nextMessageId = useRef(2)
  const activeRequest = useRef<AbortController | null>(null)
  const [progress, setProgress] = useState<SearchProgress[]>([])
  const [startedAt, setStartedAt] = useState(0)
  const lastQueryRequest = useRef(0)

  const submitExternalQuery = useEffectEvent((query: string) => {
    void submitQuery(query, performance.now())
  })

  useEffect(() => () => activeRequest.current?.abort(), [])

  useEffect(() => {
    if (externalBusy) activeRequest.current?.abort()
  }, [externalBusy])

  useEffect(() => {
    if (searching || externalBusy || !queryRequest || queryRequest.id === lastQueryRequest.current) return
    lastQueryRequest.current = queryRequest.id
    submitExternalQuery(queryRequest.query)
  }, [queryRequest, searching, externalBusy])

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages, searching])

  async function submitQuery(query: string, started: number) {
    const normalized = query.trim()
    if (normalized.length < 2 || activeRequest.current || externalBusy) return
    const controller = new AbortController()
    activeRequest.current = controller
    const trace: SearchProgress[] = []
    setProgress([])
    setStartedAt(started)

    const userMessage: ChatMessage = {
      id: nextMessageId.current++,
      role: 'user',
      text: normalized,
    }
    setMessages((current) => [...current, userMessage])
    setInput('')
    setSearching(true)

    try {
      const result = await onSearch(normalized, (event) => {
        if (controller.signal.aborted) return
        trace.push(event)
        setProgress([...trace])
      }, controller.signal)
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId.current++,
          role: 'assistant',
          text: result.answer,
          shipments: result.shipments,
          chatModel: result.chat_model,
          chatProvider: result.chat_provider,
          searchMode: result.search_mode,
          hasMore: result.has_more,
          filters: result.applied_filters,
          trace,
          outcome: 'completed',
          startedAt: started,
          durationMs: performance.now() - started,
        },
      ])
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: nextMessageId.current++,
          role: 'assistant',
          text: controller.signal.aborted
            ? '요청을 중단했습니다.'
            : error instanceof Error && error.name !== 'TimeoutError'
              ? error.message
              : '응답 대기 시간이 초과되었습니다. 다시 시도해 주세요.',
          trace,
          outcome: controller.signal.aborted ? 'cancelled' : 'failed',
          startedAt: started,
          durationMs: performance.now() - started,
        },
      ])
    } finally {
      activeRequest.current = null
      setSearching(false)
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void submitQuery(input, event.timeStamp)
  }

  function resetChat() {
    setMessages([initialMessage])
    setInput('')
    onShowAll()
  }

  return (
    <aside className="chat-panel workspace-panel" aria-label="AI 배송 도우미" lang="ko">
      <div className="panel-heading chat-heading">
        <div>
          <span className="eyebrow">Agent with Tools</span>
          <h2>Shipment assistant</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="대화 초기화"
          aria-label="대화 초기화"
          disabled={searching}
          onClick={resetChat}
        >
          <RotateCcw size={17} />
        </button>
      </div>

      <div className="chat-messages" aria-live="polite">
        {messages.map((message, messageIndex) => (
          <div className={`chat-turn ${message.role}`} key={message.id}>
            <span className="chat-avatar" aria-hidden="true">
              {message.role === 'assistant' ? (
                <Bot size={17} />
              ) : (
                <UserRound size={17} />
              )}
            </span>
            <div className="chat-turn-content">
              {message.trace ? (
                <SearchTrace events={message.trace} outcome={message.outcome ?? 'completed'} startedAt={message.startedAt ?? 0} durationMs={message.durationMs} />
              ) : null}
              {message.role === 'assistant' ? (
                <div className="chat-markdown">
                  <Markdown
                    remarkPlugins={[remarkGfm]}
                    skipHtml
                    disallowedElements={['img']}
                    components={{
                      table: ({ children }) => (
                        <div className="chat-table-scroll" role="region" aria-label="배송 정보 표" tabIndex={0}>
                          <table>{children}</table>
                        </div>
                      ),
                    }}
                  >
                    {message.text}
                  </Markdown>
                </div>
              ) : (
                <p>{message.text}</p>
              )}
              {message.searchMode && message.searchMode !== 'not_searched' ? (
                <div className="chat-search-summary">
                  <strong>{SEARCH_MODE_LABELS[message.searchMode]}</strong>
                  <span>{message.shipments?.length ?? 0}건 표시</span>
                  {message.filters ? (
                    <span>
                      {[
                        message.filters.status && `상태: ${STATUS_LABELS_KO[message.filters.status]}`,
                        message.filters.shipment_number,
                        message.filters.origin_region && `출발 권역: ${message.filters.origin_region}`,
                        message.filters.destination_region && `도착 권역: ${message.filters.destination_region}`,
                        message.filters.origin_name && `출발지: ${message.filters.origin_name}`,
                        message.filters.destination_name && `도착지: ${message.filters.destination_name}`,
                        message.filters.nearby_location && `${{ origin: '출발', destination: '도착', current: '현재' }[message.filters.position_field]} 위치: ${message.filters.nearby_location} 반경 ${message.filters.radius_km}km`,
                        message.filters.cargo_query && `화물 검색어: ${message.filters.cargo_query}`,
                        (message.filters.eta_start || message.filters.eta_end) && `ETA: ${message.filters.eta_start ?? '시작 제한 없음'} ~ ${message.filters.eta_end ?? '종료 제한 없음'} (양 끝 포함)`,
                        message.filters.sort_by === 'semantic_spatial' && '정렬: 의미 72% + 기준점 근접도 28%',
                        message.filters.sort_by === 'destination_distance' && '정렬: 현재 위치에서 각 목적지까지 가까운 순',
                        message.filters.sort_by === 'destination_distance' && !message.filters.status && '배송 완료 제외',
                        message.filters.result_limit && `요청: ${message.filters.result_limit}건`,
                      ].filter(Boolean).join(' · ')}
                    </span>
                  ) : null}
                  {message.hasMore ? <span>{message.filters?.sort_by === 'destination_distance'
                    ? '가까운 순으로 일부 결과만 표시했습니다.'
                    : '표시되지 않은 결과가 더 있습니다. 조건을 좁혀 주세요.'}</span> : null}
                </div>
              ) : null}
              {messageIndex === 0 ? (
                <div className="suggestion-list">
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion}
                      disabled={searching || externalBusy}
                      onClick={(event) => void submitQuery(suggestion, event.timeStamp)}
                    >
                      {suggestion}
                    </button>
                  ))}
                </div>
              ) : null}

              {message.shipments?.length ? (
                <div className="chat-results">
                  {message.shipments.map((shipment) => (
                    <article className={`chat-result${selectedNumber === shipment.shipment_number ? ' selected' : ''}`} key={shipment.id}>
                      <button
                        className="chat-result-select"
                        type="button"
                        aria-label={`${shipment.shipment_number} 배송 상세 보기`}
                        aria-pressed={selectedNumber === shipment.shipment_number}
                        onClick={() => onSelect(shipment)}
                      >
                      <div className="chat-result-header">
                        <strong>{shipment.shipment_number}</strong>
                        <StatusBadge status={shipment.status} label={STATUS_LABELS_KO[shipment.status]} compact />
                      </div>
                      <b>{shipment.title}</b>
                      <p>{shipment.description}</p>
                      <div className="chat-result-route">
                        <span>{shipment.origin_name}</span>
                        <ArrowRight size={12} aria-hidden="true" />
                        <span>{shipment.destination_name}</span>
                      </div>
                      {shipment.remaining_distance_km != null ? (
                        <p className="chat-result-distance">
                          목적지까지 {shipment.remaining_distance_km.toLocaleString('ko-KR', { maximumFractionDigits: 1 })} km
                          <br />지표면 최단거리
                        </p>
                      ) : null}
                      {shipment.distance_to_center_km != null ? (
                        <p className="chat-result-distance">
                          기준점까지 {shipment.distance_to_center_km.toLocaleString('ko-KR', { maximumFractionDigits: 1 })} km
                          <br />지표면 최단거리
                        </p>
                      ) : null}
                      {(message.filters?.eta_start || message.filters?.eta_end) && shipment.eta ? (
                        <p>ETA {shipment.eta}</p>
                      ) : null}
                      </button>
                      <div className="chat-result-footer">
                        <span>
                          {shipment.hybrid_score != null
                            ? `가중 점수 ${shipment.hybrid_score.toFixed(3)}`
                            : shipment.similarity !== null
                            ? `유사도 ${Math.round(shipment.similarity * 100)}%`
                            : '조건 일치'}
                        </span>
                        <button type="button" onClick={() => onLocate(shipment)}>
                          <LocateFixed size={14} />
                          현재 위치 보기
                        </button>
                      </div>
                    </article>
                  ))}
                  <span className="query-engine">
                    {message.chatProvider === 'horizondb' ? 'HorizonDB 모델 호출' : '직접 모델 호출'} · {message.chatModel} · {message.searchMode ? SEARCH_MODE_LABELS[message.searchMode] : '배송 검색'}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        ))}

        {searching ? (
          <div className="chat-turn assistant searching-turn">
            <span className="chat-avatar" aria-hidden="true">
              <Bot size={17} />
            </span>
            <div className="chat-turn-content">
              <div role="status">{progress.at(-1)?.message ?? '요청을 전송하고 있습니다.'}</div>
              <SearchTrace events={progress} outcome="running" startedAt={startedAt} />
            </div>
          </div>
        ) : null}
        <div ref={messageEnd} />
      </div>

      <form className="chat-composer" onSubmit={handleSubmit}>
        <label>
          <span className="sr-only">배송 질문 입력</span>
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && event.nativeEvent.isComposing) {
                event.preventDefault()
              }
            }}
            placeholder="배송에 관해 질문해 주세요"
            maxLength={300}
            disabled={searching || externalBusy}
          />
        </label>
        {searching ? (
          <button type="button" aria-label="요청 중단" title="요청 중단" onClick={() => activeRequest.current?.abort()}>
            <Square size={17} />
          </button>
        ) : <button
          type="submit"
          aria-label="메시지 보내기"
          title="보내기"
          disabled={input.trim().length < 2 || searching || externalBusy}
        >
          <Send size={17} />
        </button>}
      </form>
    </aside>
  )
}