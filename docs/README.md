# Fleet Intelligence 문서

HorizonShip의 현재 구현을 설명하는 한국어 발표·시연 자료입니다. 기준일은 2026-09-15입니다.
제품명 **Fleet Intelligence**, 부제 **Powered by HorizonDB**, 화면 이름 **Search Workbench**, **Agent with Tools**는 영어로 유지합니다. 본문과 설명 제목은 한국어로 작성하고 SQL·API·제품 이름은 코드와 같은 표기를 사용합니다.

## 읽는 순서

| 문서 | 용도 |
| --- | --- |
| [발표자료 HTML](fleet-intelligence-slides.html) | 브라우저에서 바로 여는 본문 13장 + 참고 5장 |
| [발표자 노트](presenter-notes.md) | 슬라이드별 설명과 실제 시연 순서 |
| [기술 설명 HTML](blog-post.html) | 목차가 있는 한국어 기술 설명 문서 |
| [기술 설명 Markdown](blog-post.md) | 검토·수정용 원고 |
| [슬라이드 Markdown](fleet-intelligence-slides.md) | 발표자료 HTML의 원고 |
| [프로젝트 가이드](../README.md) | 실행 환경, API, 검색 규칙, DB 설정 |
| [인프라 가이드](../infra/README.md) | PowerShell·Bicep 사전 조회와 승인 기반 배포 |

HTML은 별도 서버 없이 열 수 있습니다. 발표자료는 레퍼런스와 같은 1920×1080(16:9) 구성으로 화면 크기에 맞춰 전체를 축소합니다. 이전·다음 버튼, 슬라이드 선택, 방향키·Page Up/Down·Home/End로 이동합니다. 작은 화면에서는 가로 보기를 권장하며, 캡처 이미지를 누르면 원본 크기로 열 수 있습니다. 브라우저 인쇄에서는 전체 18장을 장별로 출력합니다.

레퍼런스의 네이비 표지, 옅은 격자 배경, 블루·그린·앰버 강조색과 아키텍처·화면·코드 레이아웃을 유지합니다. 한국어 본문은 Pretendard를 사용합니다. 기술 설명 HTML은 기존 스크롤 문서 형식을 유지합니다.

CSS와 JavaScript는 HTML 안에 포함됩니다. 화면 이미지는 `media`의 상대 경로를 사용하므로 공유할 때 함께 전달합니다. [출처와 라이선스 고지](THIRD-PARTY-NOTICES.md)도 함께 전달합니다. Pretendard 폰트는 버전을 고정한 CDN에서 불러오며, 연결할 수 없으면 설치된 한글 폰트를 사용합니다. 앱 캡처에는 OpenStreetMap 지도가 포함되며 원래의 저작자 표시를 유지했습니다.

## 반영한 변경

도입부 2장은 하나의 HorizonDB에서 정형·공간·벡터 데이터를 함께 저장하고 조회하는 샘플의 목적을 설명합니다. PostGIS·pgvector·DiskANN과 임베딩 갱신 pipeline의 역할을 표시하고 외부 Foundry는 데이터베이스 경계 밖에 배치했습니다. 3장은 상태·ETA·권역·화물 의미 또는 거리 정렬을 결합하는 세 가지 업무 질문으로 이어집니다. 새 질문의 실제 조건과 결과는 발표자 노트에 기록했습니다.

4장의 두 검색 경로 설명 다음에는 5장의 실제 앱 화면이 이어집니다. 6장은 검색에 필요한 정형·PostGIS·vector 컬럼과 테이블 연결만 보여줍니다. 12장의 pipeline 설명 다음에는 13장 ‘고객 데이터로 적용하는 방법’으로 본문을 마칩니다. 검색 대상과 조건, 위치·설명 필드와 정렬, 변경 후 갱신을 고객 업무에 맞추고 대표 질문과 샘플 데이터로 결과를 확인하는 방법을 제시합니다. 14~18장은 검증·운영 주의사항, 예상 계획, 전체 테이블 구조, Workbench 조작, 실행 및 배포의 참고 자료입니다.

현재 API 경로와 상태 필터 우선순위, ETA 기간, PostGIS 권역·반경 검사, 목적지 거리 정렬, 의미 72%·근접도 28% 정렬을 설명합니다. 원본과 달리 배송과 임베딩은 별도 테이블로 관리하고 기존 `on_change` pipeline을 유지합니다. 모델은 직접 API 또는 DB 함수로 호출하지만 실제 추론은 외부 Foundry에서 실행됩니다.

실행 내역은 요청별 SQL·바인딩 값·임베딩 입력을 표시합니다. 실행 계획은 선택적 `EXPLAIN (FORMAT JSON)` 예상 계획입니다. CodeMirror의 SQL 보기, 노드 선택에 따른 SQL 범위 강조, 6:4 가변 분할도 포함했습니다. 실제 실행 시간·buffer·WAL 통계로 소개하지 않습니다.

7~9장은 독립적인 복합 질의 세 가지를 질문 → 조건 → SQL 발췌 → 확인 결과 순서로 설명합니다. 리튬 배터리·상태·ETA·Asia 출발 검색, 반도체·Singapore 반경·가중 정렬, Asia 출발 지연 배송의 목적지 거리순 상위 2건입니다. SQL은 현재 Repository에서 핵심 조건·계산·정렬을 발췌한 것으로 전체 실행문이 아니며, 결과는 2026-09-15의 이전 실제 검증 기록입니다. 이번 문서 재구성에서 모델을 다시 호출하지 않았습니다.

10장은 model registry와 `azure_ai.generate`, `azure_openai.create_embeddings`, pipeline의 `ai.embed` 역할 및 외부 Foundry 경계를 설명합니다. 11장은 8장의 반도체 질문을 조건 해석 → Python 검색 도구 → 답변 생성으로 연결합니다. 12장은 검색 요청과 별개인 데이터 변경 흐름을 설명합니다. shipments trigger가 의미 필드 변경을 골라 job을 upsert하고, job의 on_change pipeline이 임베딩을 갱신합니다. 현재 청킹 단계는 없고 배송별 벡터 하나를 만듭니다. 좌표·ETA만 변경하면 새 임베딩을 요청하지 않으며 content version이 맞는 벡터만 의미 검색에 사용합니다.

`media/fleet-overview.png`, `media/fleet-eta-result.png`, `media/fleet-query-plan.png`는 현재 앱에서 캡처한 실제 화면입니다. 질의 설명용으로 추가한 `media/fleet-eta-sql.png`와 `media/fleet-weighted-sql.png`는 각각 해당 질의를 실제로 실행한 뒤 SQL·바인딩 패널 또는 SQL 영역을 잘라 캡처했습니다. 합성 결과나 원본 저장소의 캡처를 현재 화면으로 사용하지 않았습니다. 기존 기술 설명 문서의 이미지는 변경하지 않았습니다.

이전 ETA 결과·SQL 캡처는 참고 2의 발표자 노트에 보존했습니다. `media/fleet-eta-conditions.png`는 `fleet-eta-sql.png`의 조건 부분만 잘라 확대한 이미지입니다. 해당 기본 ETA 질의는 리튬 배터리·Asia 조건을 포함하지 않으므로 7장의 복합 질의 결과나 바인딩 값으로 소개하지 않습니다. 반도체 질의의 실제 SQL 캡처는 8장 노트에 연결했습니다.

## 출처와 라이선스

[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)에 출처, 참고한 커밋과 원본 MIT 라이선스를 보존했습니다. 원본 문서·이미지의 중복 보관본은 제거했으며, 발표자료에 사용하는 CSS는 [slides-base.css](slides-base.css)에 내용 변경 없이 분리했습니다. 원문과 원본 이미지는 고지 문서의 고정 커밋 링크에서 확인합니다. 현재 시연용 이미지와 영상은 유지합니다.

참고본의 `/api/search`, `default-chat`, 단일 테이블 임베딩, `EXPLAIN ANALYZE`, `azd up`·Container Apps 설명은 현재 앱의 구현을 뜻하지 않습니다. 고객 공유에는 이 폴더의 개정본을 사용합니다.

## 문서 갱신과 검사

저장소 최상위 폴더에서 실행합니다. HTML 생성기는 frontend에 이미 설치된 React·Markdown 도구만 사용하며 앱 번들에 포함되지 않습니다.

```powershell
npm --prefix frontend ci
node docs/build-docs.mjs
node docs/build-docs.mjs --check
```

Markdown 원고를 수정한 뒤 HTML을 다시 생성합니다. 발표자료는 [slides-template.mjs](slides-template.mjs)에서 슬라이드 유형별로 배치하며, [slides-base.css](slides-base.css)를 읽어 결과 HTML에 포함합니다. 원본 HTML이나 보관 폴더 없이 문서를 생성할 수 있습니다. `--check`는 로컬 링크·이미지 존재, 발표자료와 노트의 번호·제목 일치, 생성 HTML의 최신 상태를 검사합니다. 출처와 라이선스 고지의 로컬 링크도 검사합니다. 실행 전에 두 개발 서버를 시작하는 절차와 데모 주의사항은 [발표자 노트](presenter-notes.md)를 참고합니다.