import { useEffect, useRef, useState } from 'react'
import { EditorState, StateEffect, StateField } from '@codemirror/state'
import { Decoration, EditorView, drawSelection, lineNumbers } from '@codemirror/view'
import type { DecorationSet } from '@codemirror/view'
import { PostgreSQL, sql } from '@codemirror/lang-sql'
import { bracketMatching, defaultHighlightStyle, syntaxHighlighting } from '@codemirror/language'
import type { SqlRange } from '../sqlPlanRanges'
import { findSqlRange, formatSqlForDisplay } from '../sqlPlanRanges'
import type { QueryPlanNode } from '../types'

const selectRange = StateEffect.define<SqlRange | null>()
const rangeHighlight = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(value, transaction) {
    for (const effect of transaction.effects) {
      if (effect.is(selectRange)) {
        const range = effect.value
        return range && range.to > range.from
          ? Decoration.set([Decoration.mark({ class: 'cm-sql-range' }).range(range.from, range.to)])
          : Decoration.none
      }
    }
    return value.map(transaction.changes)
  },
  provide: field => EditorView.decorations.from(field),
})

const theme = EditorView.theme({
  '&': { height: '100%', fontSize: '13px', color: 'var(--ink)', backgroundColor: 'var(--surface)' },
  '.cm-scroller': { overflow: 'auto', fontFamily: 'var(--font-mono)', lineHeight: '1.8' },
  '.cm-content': { padding: '12px 0' },
  '.cm-line': { padding: '0 12px' },
  '.cm-gutters': { color: 'var(--ink-muted)', backgroundColor: 'var(--surface-muted)', borderColor: 'var(--line)' },
  '.cm-sql-range': { backgroundColor: '#fff0b0', color: 'var(--ink)', outline: '1px solid #dcae32' },
  '&.cm-focused': { outline: '2px solid var(--blue)', outlineOffset: '-2px' },
})

interface SqlViewerProps {
  source: string
  selectedNode: QueryPlanNode | null
  formatted: boolean
  wrap: boolean
}

export function SqlViewer({ source, selectedNode, formatted, wrap }: SqlViewerProps) {
  const host = useRef<HTMLDivElement>(null)
  const editor = useRef<EditorView | null>(null)
  const [formattedSql] = useState(() => formatSqlForDisplay(source))
  const displayedSql = formatted ? formattedSql.text : source
  const match = selectedNode ? findSqlRange(displayedSql, selectedNode) : null
  const from = match?.range?.from
  const to = match?.range?.to

  useEffect(() => {
    if (!host.current) return
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: displayedSql,
        extensions: [
          sql({ dialect: PostgreSQL }), lineNumbers(), drawSelection(), bracketMatching(),
          syntaxHighlighting(defaultHighlightStyle), theme, rangeHighlight,
          EditorState.readOnly.of(true), EditorView.editable.of(false),
          EditorView.contentAttributes.of({ 'aria-label': '조회 SQL', 'aria-readonly': 'true', role: 'textbox', tabindex: '0' }),
          ...(wrap ? [EditorView.lineWrapping] : []),
        ],
      }),
    })
    editor.current = view
    return () => { view.destroy(); editor.current = null }
  }, [displayedSql, wrap])

  useEffect(() => {
    const selected = from !== undefined && to !== undefined ? { from, to } : null
    editor.current?.dispatch({ effects: [
      selectRange.of(selected),
      ...(selected ? [EditorView.scrollIntoView(selected.from, { y: 'center' })] : []),
    ] })
  }, [from, to, displayedSql, wrap])

  return <>
    <div className="sql-plan-match" role="status">
      {match ? `${selectedNode?.['Node Type']} · ${match.label}${match.range ? ' (SQL 절 연결 추정)' : ''}` : 'PostgreSQL · 읽기 전용'}
      {!formattedSql.formatted ? ' · 원본 표시' : ''}
    </div>
    <div className="sql-code-viewer" ref={host} />
  </>
}