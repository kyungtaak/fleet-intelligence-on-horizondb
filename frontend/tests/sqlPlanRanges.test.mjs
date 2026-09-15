import assert from 'node:assert/strict'
import test from 'node:test'
import { findSqlRange, formatSqlForDisplay } from '../src/sqlPlanRanges.ts'

const source = `WITH query_vector AS (SELECT %s::public.vector(1536) AS embedding)
SELECT s.id, 1 - (se.embedding <=> query_vector.embedding) AS similarity
FROM horizon_ship.shipments AS s
JOIN horizon_ship.shipment_embeddings AS se ON se.shipment_id = s.id
WHERE EXISTS (SELECT 1 FROM horizon_ship.region_boundaries AS region WHERE region.name = %s)
ORDER BY similarity DESC LIMIT %s;`

function selected(sql, plan) {
  const { range } = findSqlRange(sql, plan)
  return range ? sql.slice(range.from, range.to).replace(/\s+/g, ' ') : null
}

test('PostgreSQL formatting preserves placeholders and vector operators', () => {
  const result = formatSqlForDisplay(source)
  assert.equal(result.formatted, true)
  assert.equal(result.text.match(/%s/g).length, 3)
  assert.ok(result.text.includes('<=>'))
})

for (const [view, sql] of [['original', source], ['formatted', formatSqlForDisplay(source).text]]) {
  test(`${view}: links LIMIT, ORDER BY, table reference and nested region reference`, () => {
    assert.equal(selected(sql, { 'Node Type': 'Limit' }), 'LIMIT %s')
    assert.equal(selected(sql, { 'Node Type': 'Sort' }), 'ORDER BY similarity DESC')
    assert.equal(selected(sql, { 'Node Type': 'Seq Scan', 'Relation Name': 'shipments' }), 'FROM horizon_ship.shipments AS s')
    assert.equal(selected(sql, { 'Node Type': 'Index Scan', 'Relation Name': 'region_boundaries' }), 'FROM horizon_ship.region_boundaries AS region')
    assert.equal(selected(sql, { 'Node Type': 'Nested Loop' }), null)
  })
}

test('strings and comments do not create false clause matches', () => {
  const sql = "SELECT 'ORDER BY fake LIMIT 1' FROM shipments /* LIMIT 2 */ ORDER BY id LIMIT %s;"
  assert.equal(selected(sql, { 'Node Type': 'Sort' }), 'ORDER BY id')
  assert.equal(selected(sql, { 'Node Type': 'Limit' }), 'LIMIT %s')
})

test('multiple matching subqueries and self joins are not guessed', () => {
  assert.equal(selected('SELECT * FROM (SELECT * FROM shipments ORDER BY id) AS inner_query ORDER BY id;', { 'Node Type': 'Sort' }), null)
  assert.equal(selected('SELECT * FROM shipments AS first JOIN shipments AS second ON first.id = second.id;', { 'Node Type': 'Seq Scan', 'Relation Name': 'shipments' }), null)
})

test('quoted identifiers retain their case', () => {
  assert.equal(selected('SELECT * FROM "horizon_ship"."Shipments" AS "source";', { 'Node Type': 'Seq Scan', 'Relation Name': 'Shipments' }), 'FROM "horizon_ship"."Shipments" AS "source"')
})