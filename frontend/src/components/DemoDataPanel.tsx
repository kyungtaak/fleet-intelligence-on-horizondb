import { useEffect, useRef, useState } from 'react'
import {
  Check,
  CircleAlert,
  DatabaseZap,
  Layers3,
  LoaderCircle,
  PackagePlus,
  Play,
  Search,
  Trash2,
  X,
} from 'lucide-react'
import {
  createShipment,
  createShipments,
  deleteDemoShipments,
  getEmbeddingStatus,
  updateShipment,
} from '../api'
import { buildDemoShipments, buildUpdate } from '../demoData'
import type { UpdateScenario } from '../demoData'
import type { Shipment, ShipmentEmbeddingStatus } from '../types'

type PanelMode = 'single' | 'bulk'
type SingleAction = 'update' | 'insert'
type ActivityState =
  | 'idle'
  | 'writing'
  | 'pending'
  | 'ready'
  | 'not_required'
  | 'failed'
  | 'timeout'

interface DemoDataPanelProps {
  open: boolean
  shipments: Shipment[]
  selected: Shipment | null
  onClose: () => void
  onApplied: (shipments: Shipment[], focus: Shipment | null) => void
  onDeleted: (shipmentIds: string[]) => void
  onVerify: (query: string) => void
}

const SCENARIOS: Record<
  UpdateScenario,
  { label: string; description: string }
> = {
  delay: {
    label: '운송 지연 발생',
    description: '상태, 위치, 좌표, ETA를 바꾸고 embedding을 갱신합니다.',
  },
  exception: {
    label: '예외 상황 발생',
    description: '검사 필요 상태로 바꾸고 현재 위치를 이동합니다.',
  },
  delivered: {
    label: '배송 완료',
    description: '현재 좌표를 목적지로 이동하고 완료 처리합니다.',
  },
  position: {
    label: '좌표만 이동',
    description: 'PostGIS 좌표만 바꾸며 embedding은 다시 만들지 않습니다.',
  },
}

const VERIFY_SEARCHES = [
  ['새 콜드체인 화물 검색', '콜드체인 백신과 의약품 화물을 찾아주세요'],
  ['인도적 지원 물품 찾기', '인도적 지원 물품을 찾아주세요'],
  ['재생에너지 배송 보기', '재생에너지 설비 배송을 보여주세요'],
] as const

function wait(milliseconds: number) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds))
}

export function DemoDataPanel({
  open,
  shipments,
  selected,
  onClose,
  onApplied,
  onDeleted,
  onVerify,
}: DemoDataPanelProps) {
  const [mode, setMode] = useState<PanelMode>('single')
  const [singleAction, setSingleAction] = useState<SingleAction>('update')
  const [scenario, setScenario] = useState<UpdateScenario>('delay')
  const [activity, setActivity] = useState<ActivityState>('idle')
  const [activityLabel, setActivityLabel] = useState('')
  const [embeddingStatus, setEmbeddingStatus] =
    useState<ShipmentEmbeddingStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const pollToken = useRef(0)
  const [deleting, setDeleting] = useState(false)
  const [deleteIds, setDeleteIds] = useState<string[] | null>(null)
  const [cleanupMessage, setCleanupMessage] = useState<string | null>(null)
  const [cleanupError, setCleanupError] = useState<string | null>(null)

  useEffect(() => () => {
    pollToken.current += 1
  }, [])

  const busy = deleting || activity === 'writing' || activity === 'pending'
  const demoIds = shipments.filter((shipment) =>
    shipment.metadata.demo_run === true
    && shipment.metadata.tags?.includes('pipeline-demo'),
  ).map((shipment) => shipment.id)

  async function removeDemoData() {
    if (!deleteIds || busy) return
    setDeleting(true)
    setCleanupError(null)
    try {
      const deleted = await deleteDemoShipments(deleteIds)
      pollToken.current += 1
      setActivity('idle')
      setEmbeddingStatus(null)
      setDeleteIds(null)
      setCleanupMessage(`데모 배송 ${deleted.length}건을 삭제했습니다.`)
      onDeleted(deleted)
    } catch (deleteError) {
      setCleanupError(deleteError instanceof Error ? deleteError.message : '삭제하지 못했습니다.')
    } finally {
      setDeleting(false)
    }
  }

  async function trackEmbedding(shipmentNumbers: string[]) {
    const token = ++pollToken.current
    setActivity('pending')
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const status = await getEmbeddingStatus(shipmentNumbers)
      if (token !== pollToken.current) return
      setEmbeddingStatus(status)
      if (status.total === shipmentNumbers.length && status.pending === 0) {
        setActivity('ready')
        return
      }
      await wait(750)
    }
    if (token === pollToken.current) setActivity('timeout')
  }

  function begin(label: string) {
    pollToken.current += 1
    setActivity('writing')
    setActivityLabel(label)
    setEmbeddingStatus(null)
    setError(null)
    setDeleteIds(null)
    setCleanupMessage(null)
    setCleanupError(null)
  }

  function fail(operationError: unknown) {
    setActivity('failed')
    setError(
      operationError instanceof Error
        ? operationError.message
        : '데이터 작업을 완료하지 못했습니다.',
    )
  }

  async function runSingle() {
    if (singleAction === 'update') {
      if (!selected) return
      begin(`${selected.shipment_number} 업데이트`)
      try {
        const updated = await updateShipment(
          selected.shipment_number,
          buildUpdate(selected, scenario),
        )
        onApplied([updated], updated)
        if (scenario === 'position') {
          setActivity('not_required')
          return
        }
        await trackEmbedding([updated.shipment_number])
      } catch (operationError) {
        fail(operationError)
      }
      return
    }

    begin('새 데모 배송 1건 추가')
    try {
      const created = await createShipment(buildDemoShipments(shipments, 1)[0])
      onApplied([created], created)
      await trackEmbedding([created.shipment_number])
    } catch (operationError) {
      fail(operationError)
    }
  }

  async function runBulk() {
    begin('데모 배송 20건 추가')
    try {
      const created = await createShipments(buildDemoShipments(shipments, 20))
      onApplied(created, null)
      await trackEmbedding(created.map((shipment) => shipment.shipment_number))
    } catch (operationError) {
      fail(operationError)
    }
  }

  const completed = activity === 'ready' || activity === 'not_required'
  const ready = embeddingStatus?.ready ?? 0
  const total = embeddingStatus?.total ?? 0

  return (
    <aside
      className={`demo-data-panel${open ? ' open' : ''}`}
      aria-label="데모 데이터 입력"
      aria-hidden={!open}
      lang="ko"
    >
      <header className="demo-panel-header">
        <div>
          <span className="eyebrow">HorizonDB pipeline</span>
          <h2>데모 데이터 입력</h2>
        </div>
        <button
          className="icon-button"
          type="button"
          title="데모 데이터 패널 닫기"
          aria-label="데모 데이터 패널 닫기"
          onClick={onClose}
        >
          <X size={17} />
        </button>
      </header>

      <div className="demo-panel-body">
        <div className="demo-mode-control" aria-label="입력 방식">
          <button
            type="button"
            className={mode === 'single' ? 'active' : ''}
            onClick={() => setMode('single')}
            disabled={busy}
          >
            <PackagePlus size={15} />
            단건
          </button>
          <button
            type="button"
            className={mode === 'bulk' ? 'active' : ''}
            onClick={() => setMode('bulk')}
            disabled={busy}
          >
            <Layers3 size={15} />
            벌크 20건
          </button>
        </div>

        {mode === 'single' ? (
          <section className="demo-operation">
            <label className="demo-field">
              <span>작업</span>
              <select
                value={singleAction}
                disabled={busy}
                onChange={(event) => setSingleAction(event.target.value as SingleAction)}
              >
                <option value="update">선택 배송 업데이트</option>
                <option value="insert">새 배송 1건 추가</option>
              </select>
            </label>

            {singleAction === 'update' ? (
              <>
                <div className={`demo-selection${selected ? '' : ' empty'}`}>
                  <span>선택 배송</span>
                  <strong>{selected?.shipment_number ?? '배송을 먼저 선택해 주세요'}</strong>
                  {selected ? <small>{selected.title}</small> : null}
                </div>
                <label className="demo-field">
                  <span>시나리오</span>
                  <select
                    value={scenario}
                    disabled={busy}
                    onChange={(event) => setScenario(event.target.value as UpdateScenario)}
                  >
                    {Object.entries(SCENARIOS).map(([value, item]) => (
                      <option key={value} value={value}>{item.label}</option>
                    ))}
                  </select>
                  <small>{SCENARIOS[scenario].description}</small>
                </label>
              </>
            ) : (
              <div className="demo-insert-summary">
                <DatabaseZap size={18} />
                <span>
                  <strong>콜드체인 배송 1건</strong>
                  <small>새 배송을 추가하고 검색 가능 상태까지 추적합니다.</small>
                </span>
              </div>
            )}

            <button
              className="demo-run-button"
              type="button"
              disabled={busy || (singleAction === 'update' && !selected)}
              onClick={() => void runSingle()}
            >
              {busy ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
              {singleAction === 'update' ? '업데이트 실행' : '1건 추가'}
            </button>
          </section>
        ) : (
          <section className="demo-operation bulk-operation">
            <div className="bulk-number">20</div>
            <div>
              <strong>검색용 배송 데이터</strong>
              <p>콜드체인, 인도적 지원, 재생에너지, 반도체 화물을 각 5건씩 한 transaction으로 추가합니다.</p>
            </div>
            <button
              className="demo-run-button"
              type="button"
              disabled={busy}
              onClick={() => void runBulk()}
            >
              {busy ? <LoaderCircle className="spin" size={16} /> : <Layers3 size={16} />}
              20건 추가
            </button>
          </section>
        )}

        {activity !== 'idle' ? (
          <section className={`pipeline-activity state-${activity}`} aria-live="polite">
            <div className="pipeline-title">
              <span>
                {activity === 'failed' || activity === 'timeout'
                  ? <CircleAlert size={17} />
                  : completed
                    ? <Check size={17} />
                    : <LoaderCircle className="spin" size={17} />}
              </span>
              <div>
                <strong>{activityLabel}</strong>
                <small>
                  {activity === 'writing' && 'HorizonDB에 반영하고 있습니다.'}
                  {activity === 'pending' && `${ready} / ${total || '...'}건 검색 가능`}
                  {activity === 'ready' && `${ready} / ${total}건 embedding 반영 완료`}
                  {activity === 'not_required' && '좌표만 변경되어 embedding 갱신이 필요 없습니다.'}
                  {activity === 'failed' && error}
                  {activity === 'timeout' && '처리가 계속되고 있습니다. 잠시 후 상태를 다시 확인해 주세요.'}
                </small>
              </div>
            </div>
            {activity === 'pending' || activity === 'ready' ? (
              <div className="pipeline-progress" aria-label={`${ready}/${total} 검색 가능`}>
                <span style={{ width: `${total ? (ready / total) * 100 : 0}%` }} />
              </div>
            ) : null}
            <ol className="pipeline-steps">
              <li className={activity !== 'writing' ? 'done' : 'active'}>DB 반영</li>
              <li className={activity === 'pending' ? 'active' : activity === 'ready' ? 'done' : ''}>Embedding</li>
              <li className={activity === 'ready' ? 'done' : ''}>검색 가능</li>
            </ol>
          </section>
        ) : null}

        {activity === 'ready' ? (
          <section className="demo-verify">
            <span>새 데이터 검증</span>
            {VERIFY_SEARCHES.map(([label, query]) => (
              <button key={label} type="button" onClick={() => onVerify(query)}>
                <Search size={14} />
                {label}
              </button>
            ))}
          </section>
        ) : null}

        {mode === 'bulk' ? (
          <section className="demo-cleanup" aria-label="데모 데이터 정리">
            <div className="demo-cleanup-heading">
              <span>데모 데이터 <strong>{demoIds.length}건</strong></span>
              <button
                className="icon-button"
                type="button"
                title="데모로 추가한 배송 삭제"
                aria-label="데모로 추가한 배송 삭제"
                disabled={busy || demoIds.length === 0 || deleteIds !== null}
                onClick={() => {
                  setDeleteIds(demoIds)
                  setCleanupMessage(null)
                  setCleanupError(null)
                }}
              >
                <Trash2 size={16} />
              </button>
            </div>
            {deleteIds ? (
              <div className="demo-delete-confirm">
                <p>데모로 추가한 배송 {deleteIds.length}건과 연결된 embedding을 삭제할까요? 기존 배송은 유지되며 삭제는 되돌릴 수 없습니다.</p>
                <div>
                  <button type="button" disabled={busy} onClick={() => setDeleteIds(null)}>취소</button>
                  <button className="confirm-delete" type="button" disabled={busy} onClick={() => void removeDemoData()}>
                    {deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}
                    {deleting ? '삭제 중' : `${deleteIds.length}건 삭제`}
                  </button>
                </div>
              </div>
            ) : null}
            {cleanupMessage ? <p role="status">{cleanupMessage}</p> : null}
            {cleanupError ? <p role="alert">{cleanupError}</p> : null}
          </section>
        ) : null}
      </div>
    </aside>
  )
}