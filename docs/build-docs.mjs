import assert from 'node:assert/strict'
import { readFile, writeFile, access } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createSlidesDocument } from './slides-template.mjs'

const directory = dirname(fileURLToPath(import.meta.url))
const require = createRequire(resolve(directory, '../frontend/package.json'))
const load = name => import(pathToFileURL(require.resolve(name)))
const { default: React } = await load('react')
const { renderToStaticMarkup } = await load('react-dom/server')
const { default: Markdown } = await load('react-markdown')
const { default: remarkGfm } = await load('remark-gfm')
const { unified } = await load('unified')
const { default: remarkParse } = await load('remark-parse')
const parser = unified().use(remarkParse).use(remarkGfm)
const checking = process.argv.includes('--check')
const outputs = new Set(['blog-post.html', 'fleet-intelligence-slides.html'])

const read = async name => (await readFile(resolve(directory, name), 'utf8')).replace(/\r\n/g, '\n')
const text = node => node.value ?? node.children?.map(text).join('') ?? ''
const escape = value => renderToStaticMarkup(React.createElement(React.Fragment, null, value))
const render = (source, components) => renderToStaticMarkup(React.createElement(Markdown, {
  children: source, remarkPlugins: [remarkGfm], skipHtml: true,
  components: {
    img: ({ src, alt }) => React.createElement('a', { href: src, target: '_blank', rel: 'noopener', title: '원본 이미지 열기' },
      React.createElement('img', { src, alt })),
    ...components,
  },
}))

async function validateLinks(node, baseDirectory) {
  if (node.url && !/^(?:[a-z]+:|#|\/\/)/i.test(node.url)) {
    const pathname = decodeURIComponent(node.url.split('#')[0])
    if (baseDirectory !== directory || !outputs.has(pathname)) await access(resolve(baseDirectory, pathname))
  }
  for (const child of node.children ?? []) await validateLinks(child, baseDirectory)
}

const slideSource = await read('fleet-intelligence-slides.md')
const slideTree = parser.parse(slideSource)
const headings = slideTree.children.filter(node => node.type === 'heading' && node.depth === 2)
const notes = parser.parse(await read('presenter-notes.md')).children
  .filter(node => node.type === 'heading' && node.depth === 2)
  .map(text).filter(title => title.startsWith('슬라이드 '))
assert.equal(headings.length, 18, 'Expected 18 presentation slides')
assert.deepEqual(notes, headings.map((node, index) => `슬라이드 ${index + 1} - ${text(node)}`))
for (const name of ['../README.md', '../infra/README.md', 'README.md', 'blog-post.md', 'fleet-intelligence-slides.md', 'presenter-notes.md', 'THIRD-PARTY-NOTICES.md']) {
  await validateLinks(parser.parse(await read(name)), dirname(resolve(directory, name)))
}

const themeScript = `(() => {
  const param = new URLSearchParams(window.location.search).get("scoutTheme");
  const theme = param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.setAttribute("data-theme", theme);
})();`
const theme = `
:root {
  color-scheme: light;
  --cp-bg: #f7f4ef;
  --cp-bg-elevated: #fcfbf8;
  --cp-surface: #ffffff;
  --cp-surface-soft: #f5f5f5;
  --cp-border: #dedede;
  --cp-border-strong: #919191;
  --cp-text: #242424;
  --cp-text-muted: #5c5c5c;
  --cp-text-soft: #6f6f6f;
  --cp-accent: #b11f4b;
  --cp-accent-hover: #9a1a41;
  --cp-accent-soft: rgba(177, 31, 75, 0.08);
  --cp-accent-fg: #ffffff;
  --cp-success: #16a34a;
  --cp-danger: #dc2626;
  --cp-warning: #f59e0b;
  --cp-link: #0078d4;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
  --cp-overlay: rgba(255, 255, 255, 0.8);
  --cp-panel: rgba(255, 255, 255, 0.86);
  --cp-panel-strong: rgba(255, 255, 255, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.55);
  --cp-highlight: rgba(177, 31, 75, 0.12);
}
html[data-theme="dark"] {
  color-scheme: dark;
  --cp-bg: #3d3b3a;
  --cp-bg-elevated: #343231;
  --cp-surface: #292929;
  --cp-surface-soft: #2e2e2e;
  --cp-border: #474747;
  --cp-border-strong: #5f5f5f;
  --cp-text: #dedede;
  --cp-text-muted: #919191;
  --cp-text-soft: #b0b0b0;
  --cp-accent: #fd8ea1;
  --cp-accent-hover: #fb7b91;
  --cp-accent-soft: rgba(253, 142, 161, 0.14);
  --cp-accent-fg: #1a1a1a;
  --cp-success: #4ade80;
  --cp-danger: #f87171;
  --cp-warning: #fbbf24;
  --cp-link: #4da6ff;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
  --cp-overlay: rgba(41, 41, 41, 0.88);
  --cp-panel: rgba(41, 41, 41, 0.72);
  --cp-panel-strong: rgba(41, 41, 41, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.04);
  --cp-highlight: rgba(253, 142, 161, 0.12);
}`
const baseCss = `
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css');
${theme}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--cp-surface);color:var(--cp-text);font:400 17px/1.75 "Pretendard Variable",Pretendard,"Malgun Gothic",sans-serif;letter-spacing:0}
a{color:var(--cp-link);text-underline-offset:3px}button,select{font:inherit;color:inherit;letter-spacing:0}button,select{border:1px solid var(--cp-border);background:var(--cp-surface);border-radius:4px;min-height:38px;padding:4px 10px}button{cursor:pointer}button:hover{background:var(--cp-accent-soft)}button:disabled{opacity:.4;cursor:default}a:focus-visible,button:focus-visible,select:focus-visible{outline:2px solid var(--cp-accent);outline-offset:3px}
h1,h2,h3{font-weight:750;line-height:1.3;word-break:keep-all;overflow-wrap:anywhere}h1{font-size:40px;margin:0 0 28px}h2{font-size:28px;margin:56px 0 20px}h3{font-size:22px}p{margin:0 0 20px;overflow-wrap:anywhere}strong{font-weight:700}code{font:500 .88em/1.65 Consolas,"Cascadia Mono",monospace;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:22px;background:var(--cp-surface-soft);border:1px solid var(--cp-border);border-radius:6px;overflow:auto}pre code{font-size:15px}table{width:100%;table-layout:fixed;border-collapse:collapse;margin:28px 0}th,td{border-bottom:1px solid var(--cp-border);padding:14px 16px;text-align:left;vertical-align:top;overflow-wrap:anywhere}th{background:var(--cp-surface-soft);font-weight:700}img{display:block;width:100%;height:auto;object-fit:contain;margin:24px 0;border:1px solid var(--cp-border)}blockquote{margin:20px 0;padding:16px 22px;border-left:4px solid var(--cp-accent);background:var(--cp-accent-soft)}ul,ol{padding-left:26px}header{border-bottom:1px solid var(--cp-border);background:var(--cp-surface)}.brand{font-weight:750}.eyebrow{color:var(--cp-accent);font-size:13px;font-weight:700}.meta{font-size:13px;color:var(--cp-text-muted)}
@media(max-width:760px){body{font-size:16px}h1{font-size:28px}h2{font-size:24px}th,td{padding:10px 8px;font-size:14px}pre{padding:14px}pre code{font-size:13px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{html{scroll-behavior:auto}body{font-size:10.5pt;print-color-adjust:exact;-webkit-print-color-adjust:exact}header,nav,.progress{display:none!important}h1{font-size:25pt}h2{font-size:19pt;break-after:avoid}h3{break-after:avoid}pre,blockquote,tr,img{break-inside:avoid}a{color:inherit}table{margin:12px 0}th,td{padding:8px}pre code{font-size:9pt}}
`
const document = (title, css, body, script = '') => `<!doctype html>
<html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escape(title)}</title><script>${themeScript}</script><style>${baseCss}\n${css}</style></head>
<body>${body}<script>${script}</script></body></html>\n`

const slidesDocument = createSlidesDocument({
  source: slideSource, tree: slideTree, headings, render, text, escape,
  baseCss: await read('slides-base.css'),
})

const articleSource = await read('blog-post.md')
const articleHeadings = parser.parse(articleSource).children.filter(node => node.type === 'heading' && node.depth === 2)
let headingIndex = 0
const article = render(articleSource, { h2: ({ children }) => React.createElement('h2', { id: `section-${++headingIndex}` }, children) })
const toc = articleHeadings.map((node, index) => `<a href="#section-${index + 1}">${escape(text(node))}</a>`).join('')
const articleCss = `
header{position:sticky;top:0;z-index:2;padding:14px 28px;display:flex;justify-content:space-between;gap:20px}.progress{position:fixed;top:0;left:0;height:3px;background:var(--cp-accent);width:0;z-index:3}.layout{display:grid;grid-template-columns:250px minmax(0,1fr);max-width:1360px;margin:auto}.toc{position:sticky;top:65px;height:calc(100dvh - 85px);overflow:auto;padding:30px 18px;border-right:1px solid var(--cp-border)}.toc a{display:block;padding:8px 12px;margin-bottom:3px;font-size:14px;line-height:1.5;text-decoration:none;color:var(--cp-text-muted);border-left:2px solid var(--cp-border)}.toc a[aria-current=true]{color:var(--cp-accent);background:var(--cp-accent-soft);border-color:var(--cp-accent);font-weight:650}article{min-width:0;max-width:960px;padding:52px 44px 80px}article>p{max-width:70ch}article h2{scroll-margin-top:90px}.article-footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--cp-border)}
@media(max-width:900px){.layout{display:block}.toc{position:static;height:auto;max-height:240px;border-bottom:1px solid var(--cp-border);border-right:0;padding:18px}.toc a{padding:7px 10px}article{padding:32px 22px}header{padding:12px 18px;flex-wrap:wrap;font-size:14px}}
@media print{@page{size:A4;margin:18mm}.layout{display:block}article{max-width:none;padding:0}article h2{margin-top:28px}article img{max-height:110mm}header{position:static}}
`
const articleScript = `
const headings=Array.from(document.querySelectorAll('article h2'));
const links=Array.from(document.querySelectorAll('.toc a'));
function update(){const active=headings.filter(heading=>heading.getBoundingClientRect().top<=140).at(-1)||headings[0];for(const link of links){if(link.hash==='#'+active.id)link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');}const range=document.documentElement.scrollHeight-innerHeight;document.querySelector('.progress').style.width=(range>0?scrollY/range*100:0)+'%';}
addEventListener('scroll',update,{passive:true});addEventListener('resize',update);update();
`
const articleDocument = document('Fleet Intelligence | HorizonDB 기술 설명', articleCss,
  `<div class="progress" aria-hidden="true"></div><header><a class="brand" href="fleet-intelligence-slides.html">Fleet Intelligence</a><span class="meta">한국어 기술 설명 · 2026-09-16</span></header><div class="layout"><nav class="toc" aria-label="문서 목차">${toc}</nav><article>${article}<p class="article-footer meta">HorizonShip · Powered by HorizonDB</p></article></div>`, articleScript)

for (const [name, content] of [['fleet-intelligence-slides.html', slidesDocument], ['blog-post.html', articleDocument]]) {
  if (checking) assert.equal(await read(name), content, `${name} is stale; run node docs/build-docs.mjs`)
  else await writeFile(resolve(directory, name), content, 'utf8')
}
console.log(`${checking ? 'Verified' : 'Generated'} 2 HTML documents; 18 slides/notes aligned; local links and images present.`)