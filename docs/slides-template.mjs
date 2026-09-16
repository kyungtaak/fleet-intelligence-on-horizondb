import assert from 'node:assert/strict'

export function createSlidesDocument({ source, tree, headings, render, text, escape, baseCss }) {
  assert.ok(baseCss.trim(), 'Presentation base stylesheet is required')
  const markdown = node => {
    if (node.type === 'tableCell') {
      if (!node.children.length) return ''
      return source.slice(node.children[0].position.start.offset, node.children.at(-1).position.end.offset)
    }
    return source.slice(node.position.start.offset, node.position.end.offset)
  }
  const html = nodes => nodes.map(node => render(markdown(node))).join('\n')
  const tableHtml = table => render(markdown(table)).replace('<table>', '<table class="feature-table">')
  const slideDefinitions = {
    'Fleet Intelligence': ['title', 'Customer technical demo'],
    '하나의 HorizonDB에서 업무 데이터와 AI 검색을 함께': ['purpose', 'Why this sample'],
    '상태·시간·위치·화물 의미를 한 번에 묻는다면?': ['questions', 'Combined business questions'],
    '두 진입점과 공용 Repository': ['architecture', 'Two paths, one repository'],
    '두 가지 입력 방식, 같은 배송 데이터': ['overview', 'Live application'],
    '복합 검색에 사용하는 데이터': ['data', 'Relational + spatial + vector'],
    '상태·기간·출발 권역·화물 의미로 찾기': ['query', 'Query 01 · Filters + meaning'],
    '반경 안에서 의미와 거리로 정렬하기': ['query', 'Query 02 · Radius + ranking'],
    '조건에 맞는 배송을 목적지 거리순으로 찾기': ['query', 'Query 03 · Destination distance'],
    '등록한 모델을 DB 함수에서 호출하기': ['models', 'Model registry + external inference'],
    '질문에서 검색 결과와 답변까지': ['agent', 'Microsoft Agent Framework'],
    '배송 변경에 따라 임베딩 갱신하기': ['pipeline', 'Data change → embedding update'],
    '고객 데이터로 적용하는 방법': ['adoption', 'Apply to your business'],
    'end': ['ending', ''],
    '예상 계획과 측정 시간을 구분': ['table', '참고 2 · Query diagnostics'],
    '검증 범위와 운영 적용 전 확인': ['table', '참고 1 · Validation and operations'],
    'HorizonDB에 저장하는 데이터': ['table', '참고 3 · Data storage'],
    'Search Workbench에서 직접 지정하는 조건': ['table', '참고 4 · Search controls'],
  }

  const slides = headings.map((heading, index) => {
    const start = tree.children.indexOf(heading) + 1
    const end = index + 1 < headings.length ? tree.children.indexOf(headings[index + 1]) : tree.children.length
    const nodes = tree.children.slice(start, end)
    const table = nodes.find(node => node.type === 'table')
    const rows = table?.children.slice(1) ?? []
    const imageBlock = nodes.find(node => node.type === 'paragraph' && node.children.some(child => child.type === 'image'))
    const paragraphs = nodes.filter(node => node.type === 'paragraph' && node !== imageBlock)
    const code = nodes.find(node => node.type === 'code')
    const codes = nodes.filter(node => node.type === 'code')
    const definition = slideDefinitions[text(heading)]
    assert.ok(definition, `Missing slide layout: ${text(heading)}`)
    const [kind, subtitle] = definition
    const caption = escape(subtitle)
    const title = escape(text(heading))
    const brand = '<div class="brand"><span class="brand-mark">FI</span>Azure HorizonDB</div>'
    const footer = `<div class="footer"><span>${caption} · HorizonShip</span><span>${index + 1} / ${headings.length}</span></div>`
    const header = `${brand}<p class="kicker">${caption}</p><h1>${title}</h1>`
    let className = ''
    let body

    if (kind === 'title') {
      className = 'title dark'
      body = `<div class="title-content"><p class="kicker">${caption}</p><h1>${title}</h1><div class="lead">${html(paragraphs.slice(0, 2))}</div><div class="title-tags">${text(paragraphs[2]).split(' · ').map(tag => `<span>${escape(tag)}</span>`).join('')}</div></div>`
    } else if (kind === 'ending') {
      className = 'ending-slide dark'
      body = `<h1>${title}</h1>`
    } else if (kind === 'purpose') {
      className = 'purpose-slide'
      body = `${header}<div class="purpose-intro">${html([paragraphs[0]])}</div><div class="purpose-system"><div class="purpose-database"><h2>Azure HorizonDB</h2><div class="purpose-foundation">${html([paragraphs[1]])}</div><div class="purpose-data">${rows.map(row => `<div><h3>${escape(text(row.children[0]))}</h3>${html([row.children[1]])}<p class="purpose-capability">${escape(text(row.children[2]))}</p></div>`).join('')}</div><div class="purpose-pipeline">${html([paragraphs[2]])}</div></div><div class="purpose-connection" aria-label="모델 호출과 응답">&#8596;</div><div class="purpose-model"><p class="kicker">외부 모델 서비스</p><h2>Azure AI Foundry</h2>${html([paragraphs[3]])}</div></div><div class="purpose-outcome">${html([paragraphs[4]])}</div>`
    } else if (kind === 'questions') {
      className = 'compound-questions'
      body = `${header}<div class="scenario-band ${rows.length === 4 ? 'four-columns' : ''}">${rows.map((row, rowIndex) => `<div class="scenario"><span class="scenario-number">${String(rowIndex + 1).padStart(2, '0')}</span><h3>${escape(text(row.children[0]))}</h3>${html(row.children.slice(1))}</div>`).join('')}</div><div class="architecture-note">${html(paragraphs)}</div>`
    } else if (kind === 'architecture') {
      body = `${header}<div class="architecture-grid"><div class="branch-stack">${table.children[0].children.map((cell, column) => `<div class="arch-node ${column ? 'agent' : ''}"><h3>${escape(text(cell))}</h3>${rows.map(row => html([row.children[column]])).join('')}</div>`).join('')}</div><div class="arrow" aria-hidden="true">&#8594;</div><div class="arch-node api"><h3>FastAPI +<br>Agent Framework</h3><p>입력 검사와 도구 실행</p><p>공용 Psycopg Repository가 조건을 SQL로 조합하고 값을 바인딩합니다.</p></div><div class="arrow" aria-hidden="true">&#8594;</div><div class="arch-node database"><h3>Azure HorizonDB</h3><p>배송 데이터 · PostGIS · pgvector · SQ4 DiskANN</p><p>동일한 도구 결과를 카드와 지도에 표시합니다.</p></div></div><div class="architecture-note">${html(paragraphs)}</div>`
    } else if (kind === 'overview') {
      className = 'screen-slide'
      const image = imageBlock.children.find(node => node.type === 'image')
      const labels = ['왼쪽 · 조건 검색', '가운데 · 공용 지도', '오른쪽 · 자연어 질문']
      body = `<div class="screen-header"><h1>${title}</h1><p>${caption}</p></div><div class="screen-layout"><a class="screen-image" href="${escape(image.url)}" target="_blank" rel="noopener" title="원본 이미지 열기"><img src="${escape(image.url)}" alt="${escape(image.alt)}"></a><div class="screen-notes">${paragraphs.map((node, paragraphIndex) => `<div class="screen-note ${paragraphIndex ? 'green' : 'amber'}"><strong>${labels[paragraphIndex]}</strong>${html([node])}</div>`).join('')}</div></div>`
    } else if (kind === 'data') {
      assert.equal(codes.length, 3, 'Search data slide needs three table definitions')
      const tableDefinitions = codes.map(node => {
        const [tableName, ...columns] = node.value.split('\n')
        return `<pre><code class="language-text"><mark class="table-name">${escape(tableName)}</mark>\n${escape(columns.join('\n'))}\n</code></pre>`
      })
      className = 'data-slide technical-slide'
      body = `${header}<div class="technical-intro">${html([paragraphs[0]])}</div><div class="data-relations"><div class="data-source"><h3>배송 · 정형 조건과 위치</h3>${tableDefinitions[0]}</div><div class="data-links"><div><h3>ID JOIN · shipments.id = shipment_id</h3>${tableDefinitions[1]}${html([paragraphs[1]])}</div><div><h3>공간 비교 · origin_position ↔ boundary</h3>${tableDefinitions[2]}${html([paragraphs[2]])}</div></div></div><div class="technical-note">${html([paragraphs[3]])}</div>`
    } else if (kind === 'query') {
      assert.equal(rows.length, 3, 'Query slide needs three condition groups')
      assert.equal(paragraphs.length, 3, 'Query slide needs question, result and caveat')
      const conditionGroups = rows.map(row => {
        const label = text(row.children[0])
        const category = label.includes('의미') ? 'semantic' : label.includes('상태') ? 'structured' : label.includes('정렬') ? 'ranking' : 'spatial'
        return { label, category }
      })
      const annotation = code.meta?.match(/^conditions=([0-3](?:,[0-3])*)$/)
      assert.ok(annotation, `Missing SQL condition annotations: ${text(heading)}`)
      const conditionNumbers = annotation[1].split(',').map(Number)
      const sqlLines = code.value.split('\n')
      assert.equal(conditionNumbers.length, sqlLines.length, `SQL condition annotations must match each line: ${text(heading)}`)
      const querySql = sqlLines.map((line, lineIndex) => {
        const conditionNumber = conditionNumbers[lineIndex]
        const group = conditionGroups[conditionNumber - 1]
        return `<span class="sql-line${group ? ` sql-${group.category}` : ''}" data-condition="${conditionNumber}"${group ? ` title="${escape(group.label)}"` : ''}>${escape(line)}</span>`
      }).join('\n')
      className = `query-slide technical-slide${code.value.startsWith('WITH query_vector AS') ? ' query-vector-slide' : ''}${code.value.startsWith('public.ST_Distance(') ? ' query-destination-slide' : ''}`
      body = `${header}<div class="query-question">${html([paragraphs[0]])}</div><div class="query-body"><div class="query-conditions"><h3>적용 조건</h3>${rows.map((row, rowIndex) => { const { label, category } = conditionGroups[rowIndex]; return `<div class="condition-${category}"><h4>${escape(label)}</h4>${html([row.children[1]])}</div>` }).join('')}${codes.length > 1 ? `<section class="query-score" aria-label="가중 점수 계산">${html(codes.slice(1))}<p>거리·반경은 km 단위입니다.</p></section>` : ''}</div><div class="query-sql"><h3>핵심 SQL 발췌 <span>전체 실행문 아님 · %s는 바인딩 값</span></h3><pre><code class="language-sql condition-sql">${querySql}\n</code></pre></div></div><div class="query-result">${html([paragraphs[1]])}</div><div class="query-caveat">${html([paragraphs[2]])}</div>`
    } else if (kind === 'models') {
      className = 'models-slide technical-slide'
      body = `${header}<div class="technical-intro">${html([paragraphs[0]])}</div><div class="model-boundaries"><div class="registry-definition"><h3>HorizonDB · 모델 등록</h3>${html([code])}<p>별칭 → 연결 정보<br>모델 가중치를 저장하지 않음</p></div><div class="model-calls"><h3>HorizonDB · 호출 함수</h3>${rows.map(row => `<div>${html([row.children[0], row.children[1]])}</div>`).join('')}</div><div class="model-transport"><span>외부 추론</span><b aria-hidden="true">&#8596;</b><span>호출·응답</span></div><div class="external-models"><p class="kicker">외부 서비스</p><h3>Azure AI Foundry</h3><div><strong>GPT-5.4</strong><p>조건 해석 · 답변 생성</p></div><div><strong>text-embedding-3-small</strong><p>텍스트 → 1,536차원 벡터</p></div></div></div><div class="model-boundary-note">${html([paragraphs[1]])}</div><div class="technical-note">${html([paragraphs[2]])}</div>`
    } else if (kind === 'agent') {
      className = 'agent-slide technical-slide'
      body = `${header}<div class="technical-intro">${html([paragraphs[0]])}</div><div class="loop-grid">${rows.map((row, rowIndex) => `${rowIndex ? `<div class="loop-arrow">${rowIndex === 1 ? '<small>search</small>' : '<small>도구 결과</small>'}<span aria-hidden="true">&#8594;</span></div>` : ''}<div class="loop-step"><span class="loop-number">0${rowIndex + 1}</span><h3>${escape(text(row.children[0]))}</h3><p class="file-label">${escape(text(row.children[1]))}</p>${html([row.children[2]])}${rowIndex === 0 ? '<div class="clarify-stop">clarify → 확인 질문으로 종료</div>' : ''}</div>`).join('')}</div><div class="agent-example"><div><h3>조건 JSON · 반도체 질문의 주요 인자</h3>${html([code])}</div><div><h3>검색 결과로 답변</h3>${html(paragraphs.slice(1))}</div></div>`
    } else if (kind === 'pipeline') {
      assert.equal(codes.length, 3, 'Pipeline slide needs change, version and SQL details')
      assert.equal(codes[2].lang, 'sql', 'Pipeline declaration must be SQL')
      const pipelineSql = codes[2].value.split('\n').map(line => line.trim() === "trigger => 'on_change'," ? `<mark class="pipeline-trigger">${escape(line)}</mark>` : escape(line)).join('\n')
      className = 'pipeline-slide technical-slide'
      body = `${header}<div class="technical-intro">${html([paragraphs[0]])}</div><div class="pipeline-flow">${rows.map((row, step) => `<div><span class="pipeline-number">0${step + 1}</span><h3>${escape(text(row.children[0]))}</h3>${html([row.children[1]])}${step === 1 ? '<div class="pipeline-gate">신규·입력 변경 → job<br>변경 없음 → 종료</div>' : ''}</div>`).join('')}</div><div class="pipeline-details"><div class="pipeline-rules"><h3>변경 대상과 검색 시점</h3>${html(codes.slice(0, 2))}<div class="technical-note">${html([paragraphs[1]])}</div></div><div class="pipeline-declaration"><h3>실제 pipeline 선언 <span>%s는 실행 시 바인딩 값</span></h3><pre><code class="language-sql">${pipelineSql}</code></pre></div></div>`
    } else if (kind === 'adoption') {
      assert.equal(rows.length, 3, 'Customer adoption slide needs three adaptation areas')
      assert.equal(paragraphs.length, 2, 'Customer adoption slide needs introduction and closing statement')
      className = 'adoption-slide'
      body = `${header}<div class="adoption-intro">${html([paragraphs[0]])}</div><div class="adoption-comparison">${tableHtml(table)}</div><div class="adoption-next">${html([paragraphs[1]])}</div>`
    } else {
      body = `${header}${tableHtml(table)}<div class="architecture-note">${html(paragraphs)}</div>`
    }
    return `<section class="slide ${className}${index === 0 ? ' active' : ''}" id="slide-${index + 1}" aria-label="${title}"${index ? ' hidden' : ''}>${body}${kind === 'ending' ? '' : footer}</section>`
  }).join('\n')

  const options = headings.map((node, index) => `<option value="${index}">${index + 1}. ${slideDefinitions[text(node)][1].startsWith('참고') ? '[참고] ' : ''}${escape(text(node))}</option>`).join('')
  return `<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Fleet Intelligence | 한국어 발표자료</title>
<style>@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css');
${baseCss}
:root{font-family:"Pretendard Variable",Pretendard,"Malgun Gothic",sans-serif;color-scheme:light}
body{display:block}h1,h2,h3,p,td,th{word-break:keep-all;overflow-wrap:anywhere}h1{max-width:1500px;font-size:64px;line-height:1.18}p{margin-bottom:18px}.slide[hidden]{display:none}.slide p:last-child{margin-bottom:0}a{color:var(--blue);text-underline-offset:5px}a:focus-visible,button:focus-visible,select:focus-visible{outline:3px solid var(--blue);outline-offset:4px}code{font-family:"Cascadia Mono",Consolas,monospace;font-size:.88em;word-break:normal;overflow-wrap:anywhere}pre code{font:inherit}pre{white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal}table{table-layout:fixed}.feature-table td:nth-child(2){font-family:inherit;font-size:24px}.feature-table td,.feature-table th{font-size:24px;line-height:1.5;padding:26px}.feature-table td:first-child{width:420px}.feature-table p{margin:0}.architecture-note{font-size:26px;line-height:1.55}.after-grid{margin-top:48px;font-size:28px}.agenda-item{min-height:175px}.agenda-item p{color:var(--muted);font-size:26px;line-height:1.45}.scenario-band.four-columns{grid-template-columns:repeat(4,minmax(0,1fr))}.scenario{padding:38px 30px}.scenario h3{font-size:32px;line-height:1.45;min-height:94px}.scenario p{font-size:25px}.scenario-band{margin-top:56px}.architecture-grid{grid-template-columns:470px 90px 510px 90px 570px;margin-top:40px}.arch-node{padding:24px 28px}.arch-node p{font-size:24px;margin-top:10px}.arch-node.api,.arch-node.database{min-height:460px}.arch-node code{font-size:21px}.title{background-image:url('media/fleet-overview.png')}.title-content{width:1500px;padding-top:210px}.title h1{font-size:100px;line-height:1.08}.title .lead{font-size:36px;line-height:1.55}.title .lead strong{font-size:40px}.title-tags{flex-wrap:wrap}.screen-header{height:110px;gap:32px}.screen-header h1{max-width:1380px;font-size:44px;line-height:1.3}.screen-header p{white-space:nowrap;font-size:19px}.screen-layout{height:820px;grid-template-columns:minmax(0,1fr) 350px}.screen-image{min-width:0;min-height:0;display:block}.screen-note{font-size:24px;line-height:1.65;padding:26px}.screen-note strong{font-size:26px}.screen-note code{font-size:20px}.screen-slide .footer{left:52px;right:52px}.loop-step{min-height:275px}.loop-step p{font-size:26px}.adapter-grid pre{font-size:24px;line-height:1.55;height:290px}.guard-callout{font-size:25px;line-height:1.5}.query-layout{margin-top:64px;grid-template-columns:1.1fr .9fr}.query-layout pre{height:530px;font-size:29px;line-height:1.8;padding:36px}.query-layout .file-label{font-size:23px}.plan-choice p{font-size:28px;line-height:1.6}.plan-choice h3{font-size:32px}.setup-step{min-height:150px}.setup-step strong{font-size:28px}.supporting-copy{margin-top:24px;font-size:25px;line-height:1.55}.setup-flow+.supporting-copy>p:first-child{display:none}.setup-flow~.feature-table{margin-top:28px}.setup-flow~.feature-table td{padding:18px 24px}.setup-flow~.guard-callout{margin-top:20px}.insight-panel pre{height:270px;font-size:26px;line-height:1.6}.insight-panel .supporting-copy{font-size:27px;line-height:1.6}.recap-grid{grid-template-columns:1fr 1fr;gap:50px}.recap-item p{font-size:24px}.value-block p{font-size:29px;line-height:1.6}.value-block strong{font-size:36px}
.screen-note p strong{display:inline;margin:0;font-size:inherit}.plan-choice p code{display:inline;font-size:.88em;line-height:inherit}
.purpose-slide h1,.compound-questions h1{max-width:1736px;font-size:58px}.purpose-intro{font-size:28px;line-height:1.55;max-width:1660px;margin:22px 0 32px}.purpose-system{display:grid;grid-template-columns:minmax(0,1fr) 72px 390px;align-items:center;gap:18px}.purpose-database{border:2px solid var(--blue);border-radius:6px;padding:30px;background:rgba(255,255,255,.86)}.purpose-database h2{font-size:36px;margin-bottom:12px}.purpose-foundation{font-size:24px;color:var(--muted);margin-bottom:28px}.purpose-data{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:24px}.purpose-data>div{border-left:5px solid var(--blue);padding-left:20px}.purpose-data>div:nth-child(2){border-color:var(--green)}.purpose-data>div:nth-child(3){border-color:var(--amber)}.purpose-data h3{font-size:29px}.purpose-data p{font-size:25px;line-height:1.5;min-height:75px;margin:12px 0}.purpose-data .purpose-capability{font-size:23px;color:var(--muted);min-height:0;margin-bottom:0}.purpose-pipeline{border-top:1px solid var(--line);margin-top:30px;padding-top:22px;font-size:25px;line-height:1.5}.purpose-connection{font-size:56px;color:var(--blue);text-align:center}.purpose-model{border-left:6px solid var(--amber);padding:24px;background:rgba(255,255,255,.86)}.purpose-model .kicker{margin:0 0 16px;font-size:20px}.purpose-model h2{font-size:32px;line-height:1.3}.purpose-model>p:last-child{font-size:25px;line-height:1.6;color:var(--muted)}.purpose-outcome{margin-top:30px;font-size:30px;line-height:1.55;font-weight:600;max-width:1660px}.compound-questions .scenario-band{margin-top:40px}.compound-questions .scenario h3{font-size:29px;line-height:1.45;min-height:245px;margin-top:32px}.compound-questions .scenario p{font-size:24px;line-height:1.5;min-height:108px}.compound-questions .architecture-note{margin-top:28px}
.query-example .screen-layout{grid-template-columns:minmax(0,1fr) 430px}.query-example .screen-note{padding:22px;font-size:24px;line-height:1.5}.query-example .screen-note code{font-size:22px}.screen-context{font-size:29px;line-height:1.5;margin:0 0 24px;min-height:88px}.with-question .screen-layout{height:700px}
.eta-evidence{display:grid;grid-template-columns:minmax(0,1fr) 390px;gap:24px;align-items:center;min-width:0}.eta-evidence .screen-image{height:820px}.eta-bindings{min-width:0}.eta-bindings h3{font-size:26px;margin-bottom:18px}.eta-bindings pre{height:auto;font-size:28px;line-height:1.65;padding:24px}
.slide.title{background-image:url('media/fleet-overview.png');background-position:center;background-size:cover}
.technical-slide h1{font-size:58px;max-width:1736px}.technical-slide h3{font-size:27px;line-height:1.4;margin:0 0 16px}.technical-slide pre{font-size:25px;line-height:1.55;margin:0;padding:24px;height:auto;background:var(--navy);color:var(--paper);border-radius:6px}.technical-slide pre code{font:inherit}.technical-intro{font-size:28px;line-height:1.5;margin:24px 0 30px}.technical-note{font-size:24px;line-height:1.5;color:var(--muted);margin-top:24px}
.data-relations{display:grid;grid-template-columns:680px minmax(0,1fr);gap:100px;align-items:start}.data-source pre{font-size:30px;line-height:1.6;padding:30px}.data-links{display:grid;gap:30px}.data-links>div{position:relative;border-left:5px solid var(--green);padding-left:28px}.data-links>div:last-child{border-color:var(--amber)}.data-links pre{font-size:26px;padding:20px}.data-links p{font-size:24px;line-height:1.5;margin-top:16px}.relation-arrow{position:absolute;left:-85px;top:80px;font-size:50px;color:var(--blue)}
.query-question{font-size:29px;line-height:1.5;min-height:88px;margin:24px 0}.query-body{display:grid;grid-template-columns:570px minmax(0,1fr);gap:44px;height:480px}.query-conditions>div{border-left:5px solid var(--blue);padding-left:20px;margin-top:26px}.query-conditions>div:nth-of-type(2){border-color:var(--green)}.query-conditions>div:nth-of-type(3){border-color:var(--amber)}.query-conditions h4{font-size:27px;margin:0 0 10px}.query-conditions p{font-size:26px;line-height:1.5}.query-sql h3{display:flex;justify-content:space-between;align-items:baseline;gap:16px}.query-sql h3 span{font-size:20px;color:var(--muted);font-weight:400}.query-sql pre{font-size:25px;line-height:1.45;padding:20px 24px}.query-result{border-top:2px solid var(--green);margin-top:24px;padding-top:18px;font-size:28px;line-height:1.5}.query-caveat{font-size:23px;line-height:1.5;color:var(--muted);margin-top:14px}
.model-boundaries{display:grid;grid-template-columns:480px minmax(0,1fr) 70px 390px;gap:28px;align-items:stretch;min-height:470px}.registry-definition{border-left:5px solid var(--blue);padding-left:24px}.registry-definition pre{font-size:24px;padding:20px}.registry-definition>p{font-size:25px;line-height:1.6;margin-top:24px}.model-calls>div{border-bottom:1px solid var(--line);padding:20px 0}.model-calls>div p{font-size:25px;line-height:1.5;margin-bottom:10px}.model-calls>div p:first-child{color:var(--blue);font-weight:650}.model-calls code{font-size:23px}.model-transport{display:flex;align-items:center;justify-content:center;font-size:56px;color:var(--blue)}.external-models{border-left:5px solid var(--amber);padding-left:28px}.external-models .kicker{font-size:20px;margin-bottom:16px}.external-models h3{font-size:32px}.external-models>div{margin-top:44px}.external-models strong{font-size:26px;overflow-wrap:anywhere}.external-models p{font-size:25px;line-height:1.5;margin-top:12px}.model-boundary-note{font-size:30px;line-height:1.5;margin-top:34px}
.agent-slide .loop-grid{margin-top:0;gap:18px}.agent-slide .loop-step{min-height:230px;padding:24px}.agent-slide .loop-step h3{font-size:30px}.agent-slide .loop-step p{font-size:25px;line-height:1.45}.agent-slide .loop-number{font-size:30px;margin-bottom:12px}.agent-example{display:grid;grid-template-columns:1fr 1fr;gap:44px;margin-top:30px}.agent-example pre{font-size:25px;line-height:1.4;padding:20px 24px}.agent-example>div:last-child{border-left:5px solid var(--green);padding-left:30px}.agent-example p{font-size:27px;line-height:1.6}
.pipeline-flow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:34px;margin-top:28px}.pipeline-flow>div{position:relative;border-top:4px solid var(--blue);padding:20px 0 0;min-height:220px}.pipeline-flow>div:nth-child(3){border-color:var(--amber)}.pipeline-flow>div:nth-child(4),.pipeline-flow>div:nth-child(5){border-color:var(--green)}.pipeline-flow>div:not(:last-child)::after{content:'→';position:absolute;right:-29px;top:20px;font-size:30px;color:var(--muted)}.pipeline-number{font:700 30px Consolas,monospace;color:var(--blue);display:block;margin-bottom:16px}.pipeline-flow p{font-size:25px;line-height:1.5}.pipeline-flow code{font-size:22px;overflow-wrap:anywhere}.pipeline-details{display:grid;grid-template-columns:1fr 1fr;gap:44px;margin-top:32px}.pipeline-details pre{font-size:26px;line-height:1.65}
.deck-nav{position:fixed;bottom:8px;right:18px;z-index:20;display:flex;align-items:center;gap:8px;background:var(--navy);color:var(--paper);padding:6px 8px;border-radius:5px;box-shadow:0 4px 12px rgba(23,35,53,.18)}.deck-nav select,.deck-nav button{font:inherit;font-size:12px;border:1px solid var(--muted);border-radius:3px;background:var(--navy);color:var(--paper);height:30px}.deck-nav select{max-width:280px;min-width:0;text-overflow:ellipsis}.deck-nav button{width:32px;cursor:pointer}.deck-nav button:disabled{opacity:.35;cursor:default}.deck-nav output{font:13px Consolas,monospace;min-width:52px;text-align:center}body.rendering .deck-nav{display:none}
.data-source pre{line-height:1.5}.data-relations{gap:70px}.query-body{height:515px}.query-sql pre{height:440px;box-sizing:border-box}.query-caveat{color:var(--navy);font-size:24px}.query-conditions>div.condition-semantic{border-color:var(--amber)}.query-conditions>div.condition-structured{border-color:var(--blue)}.query-conditions>div.condition-spatial{border-color:var(--green)}.query-conditions>div.condition-ranking{border-color:var(--blue)}.query-score{margin-top:22px}.query-score pre{background:transparent;color:var(--navy);font-family:inherit;font-size:23px;line-height:1.5;padding:0;box-shadow:none;border:0}.query-score p{font-size:21px;color:var(--muted);margin-top:8px}.registry-definition pre{font-size:23px;white-space:pre;overflow-wrap:normal}.external-models strong{white-space:nowrap}.model-transport{flex-direction:column;gap:12px}.model-transport span{font-size:20px;line-height:1.4;text-align:center}.agent-slide .loop-arrow{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px}.agent-slide .loop-arrow small{font-size:18px;line-height:1.4;color:var(--navy);white-space:nowrap}.agent-slide .loop-step p{color:var(--navy)}.clarify-stop{border-top:1px solid var(--line);margin-top:16px;padding-top:12px;font-size:22px;line-height:1.4;color:var(--navy)}.pipeline-gate{margin-top:16px;font-size:22px;line-height:1.5;color:var(--navy)}.pipeline-details pre{font-family:inherit;font-weight:500}.deployment-slide p code{white-space:nowrap}.deployment-slide pre{background:var(--navy);color:var(--paper)}.deployment-slide .insight-panel>p{font-size:23px}
.model-boundaries{grid-template-columns:480px minmax(0,1fr) 100px 390px}.model-transport span{white-space:nowrap}
.pipeline-declaration pre{tab-size:2}.pipeline-trigger{background:rgba(7,134,87,.3);color:#b8f5d5;font-weight:700}
.pipeline-slide .pipeline-flow{margin-top:20px}.pipeline-slide .pipeline-flow>div{min-height:185px;padding-top:14px}.pipeline-slide .pipeline-number{font-size:26px;margin-bottom:8px}.pipeline-slide .pipeline-flow h3{font-size:25px;margin-bottom:10px}.pipeline-slide .pipeline-flow p{font-size:23px;line-height:1.4}.pipeline-slide .pipeline-gate{font-size:20px;margin-top:10px}.pipeline-slide .pipeline-details{grid-template-columns:550px minmax(0,1fr);gap:44px;margin-top:24px}.pipeline-rules pre{background:transparent;color:var(--navy);padding:0;border:0;box-shadow:none;font-size:24px;line-height:1.4}.pipeline-rules pre+pre{margin-top:22px}.pipeline-rules .technical-note{font-size:22px;line-height:1.45;margin-top:22px}.pipeline-declaration h3{display:flex;justify-content:space-between;align-items:baseline;gap:16px}.pipeline-declaration h3 span{font-size:19px;color:var(--muted);font-weight:400;white-space:nowrap}.pipeline-declaration pre{font-family:"Cascadia Mono",Consolas,monospace;font-size:22px;line-height:1.25;padding:20px;white-space:pre;overflow-wrap:normal;font-weight:400}
.adoption-slide h1{font-size:64px;max-width:1736px}.adoption-intro{font-size:29px;line-height:1.55;margin:26px 0 38px}.adoption-comparison .feature-table{margin:0;box-shadow:none;border-radius:0}.adoption-comparison .feature-table th{font-size:24px;padding:20px 26px;background:var(--navy);color:var(--paper)}.adoption-comparison .feature-table th:first-child{width:310px}.adoption-comparison .feature-table th:nth-child(2){width:620px}.adoption-comparison .feature-table td{font-family:inherit;font-size:28px;line-height:1.55;padding:30px 26px;background:transparent;border-bottom:1px solid var(--line)}.adoption-comparison .feature-table td:first-child{width:310px;font-size:29px;font-weight:700;border-left:6px solid var(--blue)}.adoption-comparison .feature-table tr:nth-child(2) td:first-child{border-left-color:var(--green)}.adoption-comparison .feature-table tr:nth-child(3) td:first-child{border-left-color:var(--amber)}.adoption-comparison .feature-table td:nth-child(2){color:var(--muted)}.adoption-comparison .feature-table td:nth-child(3){font-weight:600}.adoption-next{margin-top:42px;max-width:1650px;font-size:38px;line-height:1.55;color:var(--navy)}.adoption-next strong{font-weight:750}
.data-slide .table-name{padding:2px 8px;border-radius:3px;background:color-mix(in srgb,var(--amber) 45%,var(--paper));color:var(--navy);font-weight:700}
.query-sql .condition-sql{display:block;white-space:normal;tab-size:2}.sql-line{display:block;min-height:1lh;white-space:pre-wrap;border-left:6px solid var(--sql-accent,transparent);padding-left:14px}.sql-structured,.sql-ranking{--sql-accent:var(--blue)}.sql-spatial{--sql-accent:var(--green)}.sql-semantic{--sql-accent:var(--amber)}.sql-line[data-condition]:not([data-condition="0"]){background:color-mix(in srgb,var(--sql-accent) 14%,transparent)}
.query-destination-slide .query-conditions>div.condition-ranking{border-color:var(--amber)}.query-destination-slide .sql-ranking{--sql-accent:var(--amber)}
.query-vector-slide .query-sql pre{height:460px;font-size:23px;line-height:1.3;tab-size:2}
.ending-slide{padding:0;text-align:center}.slide.ending-slide.active{display:grid;place-items:center}.ending-slide h1{margin:0;font-size:100px;line-height:1.2}
@media(max-width:600px){.deck-nav{left:8px;right:8px;justify-content:center}.deck-nav select{flex:1;max-width:none}}
@media print{@page{size:1920px 1080px;margin:0}html,body{height:auto;overflow:visible;background:white}#deck{position:static;transform:none!important;left:0!important;top:0!important}.slide,.slide[hidden]{display:block!important;break-after:page;print-color-adjust:exact;-webkit-print-color-adjust:exact}.slide.ending-slide{display:grid!important;place-items:center}.slide:last-child{break-after:auto}.deck-nav{display:none}}
</style></head><body><main id="deck">${slides}</main><nav class="deck-nav" aria-label="발표자료 이동"><button id="previous" type="button" aria-label="이전 슬라이드" title="이전 슬라이드">&#8592;</button><select id="slide-picker" aria-label="슬라이드 선택">${options}</select><button id="next" type="button" aria-label="다음 슬라이드" title="다음 슬라이드">&#8594;</button><output id="counter" aria-live="polite"></output></nav>
<script>
const slides=Array.from(document.querySelectorAll('.slide'));
const deck=document.querySelector('#deck');
const picker=document.querySelector('#slide-picker');
const previous=document.querySelector('#previous');
const next=document.querySelector('#next');
const counter=document.querySelector('#counter');
const rendering=new URLSearchParams(location.search).has('render');
if(rendering)document.body.classList.add('rendering');
let current=0;
function fit(){const width=document.documentElement.clientWidth;const height=document.documentElement.clientHeight;const scale=rendering?1:Math.min(width/1920,Math.max(1,height-54)/1080);deck.style.transform='scale('+scale+')';deck.style.left=(rendering?0:(width-1920*scale)/2)+'px';deck.style.top=(rendering?0:(height-54-1080*scale)/2)+'px';}
function show(index,updateHash=true){current=Math.max(0,Math.min(slides.length-1,index));slides.forEach((slide,position)=>{slide.hidden=position!==current;slide.classList.toggle('active',position===current)});picker.value=String(current);previous.disabled=current===0;next.disabled=current===slides.length-1;counter.textContent=(current+1)+' / '+slides.length;if(updateHash)history.replaceState(null,'','#'+slides[current].id);fit();}
function fromHash(){const index=slides.findIndex(slide=>slide.id===location.hash.slice(1));show(index<0?0:index,false);}
previous.addEventListener('click',()=>show(current-1));next.addEventListener('click',()=>show(current+1));picker.addEventListener('change',()=>show(Number(picker.value)));
addEventListener('keydown',event=>{if(event.altKey||event.ctrlKey||event.metaKey||event.target.closest('select,input,textarea,button,a'))return;const destination={ArrowRight:current+1,ArrowLeft:current-1,PageDown:current+1,PageUp:current-1,Home:0,End:slides.length-1,' ':current+1}[event.key];if(destination!==undefined){event.preventDefault();show(destination);}});
addEventListener('hashchange',fromHash);addEventListener('resize',fit);fromHash();
</script></body></html>\n`
}