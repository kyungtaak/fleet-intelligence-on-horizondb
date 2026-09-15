import { PostgreSQL } from '@codemirror/lang-sql'
import { format } from 'sql-formatter'
import type { QueryPlanNode } from './types'

export interface SqlRange {
  from: number
  to: number
}

export interface SqlPlanMatch {
  range: SqlRange | null
  label: string
}

type SyntaxNode = ReturnType<typeof PostgreSQL.language.parser.parse>['topNode']

function children(node: SyntaxNode): SyntaxNode[] {
  const result: SyntaxNode[] = []
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (!child.name.includes('Comment')) result.push(child)
  }
  return result
}

export function formatSqlForDisplay(source: string): { text: string; formatted: boolean } {
  try {
    return {
      text: format(source, { language: 'postgresql', keywordCase: 'upper', paramTypes: { custom: [{ regex: '%s' }] } }),
      formatted: true,
    }
  } catch {
    return { text: source, formatted: false }
  }
}

export function findSqlRange(source: string, plan: QueryPlanNode): SqlPlanMatch {
  const tree = PostgreSQL.language.parser.parse(source)
  const scopes: SyntaxNode[][] = []
  tree.iterate({ enter(reference) {
    if (reference.name !== 'Statement' && reference.name !== 'Parens') return
    const tokens = children(reference.node)
    if (tokens.some(token => token.name === 'Keyword' && source.slice(token.from, token.to).toUpperCase() === 'SELECT')) scopes.push(tokens)
  } })
  const keyword = (token: SyntaxNode | undefined) => token?.name === 'Keyword' ? source.slice(token.from, token.to).toUpperCase() : ''
  const identifier = (token: SyntaxNode) => {
    const last = token.name === 'CompositeIdentifier' ? token.lastChild ?? token : token
    const value = source.slice(last.from, last.to)
    return value.startsWith('"') ? value.slice(1, -1).replaceAll('""', '"') : value.toLowerCase()
  }
  const candidates: SqlRange[] = []
  const nodeType = plan['Node Type']
  const clause = nodeType === 'Limit' ? 'LIMIT'
    : ['Sort', 'Incremental Sort'].includes(nodeType) ? 'ORDER'
      : nodeType === 'Aggregate' ? 'GROUP' : null
  const relation = plan['Relation Name']
  const boundaries = new Set(['WHERE', 'GROUP', 'HAVING', 'WINDOW', 'ORDER', 'LIMIT', 'OFFSET', 'FETCH', 'UNION', 'EXCEPT', 'INTERSECT', 'FOR'])

  for (const tokens of scopes) {
    tokens.forEach((token, index) => {
      if (clause && keyword(token) === clause && (clause === 'LIMIT' || keyword(tokens[index + 1]) === 'BY')) {
        let last = token
        for (const next of tokens.slice(index + 1)) {
          if (boundaries.has(keyword(next)) || next.name === ')' || next.name === ';') break
          last = next
        }
        candidates.push({ from: token.from, to: last.to })
      }
      if (!relation || !['FROM', 'JOIN'].includes(keyword(token))) return
      const table = tokens[index + 1]
      if (!table || !['Identifier', 'QuotedIdentifier', 'CompositeIdentifier'].includes(table.name) || identifier(table) !== relation) return
      let last = table
      const alias = keyword(tokens[index + 2]) === 'AS' ? tokens[index + 3] : tokens[index + 2]
      if (alias && ['Identifier', 'QuotedIdentifier'].includes(alias.name)) last = alias
      candidates.push({ from: token.from, to: last.to })
    })
  }
  if (candidates.length !== 1) return { range: null, label: candidates.length ? '여러 SQL 범위와 일치' : '직접 연결되는 SQL 범위 없음' }
  return { range: candidates[0], label: clause === 'ORDER' ? 'ORDER BY' : clause === 'GROUP' ? 'GROUP BY' : clause ?? `${relation} 참조` }
}