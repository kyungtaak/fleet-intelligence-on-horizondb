# HorizonShip 인프라 배포

HorizonDB 기본 배포와 Foundry 선택 배포를 별도 스크립트로 제공합니다. 기본 리전은 West US 3입니다.
기존 Foundry에 필요한 모델이 있으면 HorizonDB만 배포하고 외부 endpoint를 사용합니다.
등록 작업은 PowerShell이 처리하고, 리소스 그룹과 서비스는 Bicep으로 배포합니다.
스크립트의 기본 모드는 조회 전용인 `Check`입니다. 실제 변경은 모드를 명시하고 확인 문구를 입력해야 시작됩니다.

## 구성

| 파일 | 역할 |
| --- | --- |
| [deploy.ps1](deploy.ps1) | HorizonDB만 등록·검사·what-if·승인 후 배포 |
| [deploy-foundry.ps1](deploy-foundry.ps1) | 선택 실행: Foundry 등록·모델·quota 검사·what-if·승인 후 배포 |
| [subscription.bicep](subscription.bicep), [main.bicep](main.bicep) | DB용 리소스 그룹, HorizonDB, parameter group, DB 방화벽 |
| [foundry-subscription.bicep](foundry-subscription.bicep), [foundry.bicep](foundry.bicep) | Foundry용 리소스 그룹, Entra ID 전용 Foundry, 두 모델, 선택적 백엔드 RBAC |
| [foundry-project.bicep](foundry-project.bicep) | 기존 Foundry 아래 project만 별도 생성 |
| [../azure.yaml](../azure.yaml), [azd-main.bicep](azd-main.bicep) | 기존 또는 신규 HorizonDB를 선택하는 Container Apps 배포 |
| [../azd-hooks/configure.ps1](../azd-hooks/configure.ps1) | azd 환경과 비밀 값 대화형 설정 |
| [main.bicepparam](main.bicepparam) | 실행 프로세스의 환경 변수에서 배포 설정과 비밀번호 전달 |
| [foundry.bicepparam](foundry.bicepparam) | Foundry 배포 설정만 전달, DB 비밀번호 불필요 |
| [Test-Deployment.ps1](Test-Deployment.ps1) | 실제 Azure 호출 없이 제어 흐름을 검사하는 로컬 테스트 |

기본 구성은 개발 샘플용입니다. HorizonDB는 PostgreSQL 17, 2 vCore, `replicaCount=1`,
`BestEffort`를 사용하며 영역 장애에 대한 고가용성을 보장하는 구성은 아닙니다.
Foundry는 `AIServices/S0`이며 `gpt-5.4` 버전 `2026-03-05`와
`text-embedding-3-small` 버전 `1`을 Global Standard, capacity 각각 10으로 배포합니다.
capacity는 모델별 quota 단위이며 요청 건수나 토큰 수 자체가 아닙니다.

DB 접속용 비밀번호 인증은 유지합니다. 채팅과 검색어 임베딩은 provider 설정에 따라 backend에서 직접
API를 호출하거나 HorizonDB의 모델 함수를 호출합니다. 실제 추론은 두 경로 모두 외부 모델에서 실행됩니다.
배송 데이터 변경 후 벡터를 갱신하는 `azure_ai` pipeline은 DB가 Foundry를 직접 호출하며,
현재 구성에서는 key 인증이 가능한 외부 Foundry가 필요합니다.

모델 이름은 백엔드 기본값과 일치합니다. 두 provider 모두 리소스의 모델 endpoint를 사용하므로
Foundry 전용 배포에는 project를 포함하지 않습니다. 포털에서 모델을 확인하고 테스트할 때는
아래 project 전용 템플릿으로 추가합니다. 호스팅된 Agent Service는 사용하지 않으며,
웹 애플리케이션 호스팅은 다음 Container Apps 배포로 별도 구성합니다.

## Azure Container Apps 배포

루트의 `azure.yaml`은 앱 호스팅과 선택적 HorizonDB 생성을 한 `azd up` 흐름으로 묶습니다.
Foundry와 모델 deployment는 이 흐름에서 생성하거나 변경하지 않습니다. 기존 Azure OpenAI endpoint,
subscription key, `gpt-5.4`, `text-embedding-3-small` deployment가 먼저 준비되어 있어야 합니다.

PowerShell 7.4 이상, Azure CLI, [Azure Developer CLI](https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/install-azd) 1.15.0 이상이 필요합니다.
Azure CLI와 azd에 각각 로그인한 뒤 저장소 루트에서 설정 스크립트를 실행합니다.

```powershell
az login
azd auth login
azd version
```

현재 hook은 `westus3`만 허용합니다. 대상 구독에 `Microsoft.App`, `Microsoft.ContainerRegistry`,
`Microsoft.ManagedIdentity`, `Microsoft.HorizonDB`가 등록되어 있어야 하며 hook이 자동 등록하지는 않습니다.
리소스 배포 외에 앱 Identity의 ACR Pull 역할을 만들 권한도 필요합니다.

배포되는 앱 리소스는 ACR Basic, Container Apps Environment, frontend와 backend Container App,
각 앱의 User Assigned Managed Identity와 ACR Pull 역할입니다. frontend만 public ingress를 사용합니다.
Nginx가 같은 origin의 `/api` 요청을 내부 backend ingress로 전달합니다.
설정 스크립트는 두 provider를 `azure_openai`로 저장합니다. `horizondb`로 변경하려면 대상 DB에
모델 별칭을 먼저 준비해야 하며, 현재 azd 사전 검사는 provider와 관계없이 subscription key를 요구합니다.

### 기존 HorizonDB 사용

현재 배포된 HorizonDB를 그대로 사용할 때는 저장소 루트에서 다음 설정 스크립트를 실행합니다.
스크립트가 DB 비밀번호와 Azure OpenAI subscription key를 화면에 표시하지 않는 입력으로 받습니다.
`OpenAiEndpoint`에는 현재 사용 중인 리소스 endpoint를 입력합니다.

```powershell
./azd-hooks/configure.ps1 `
	-EnvironmentName demo `
	-SubscriptionId 'b214e225-c96c-489e-a778-a1f25bd40cdb' `
	-HorizonDbMode existing `
	-ResourceGroupName 'rg-horizonship-app-demo-wus3' `
	-ExistingHorizonDbResourceGroup 'rg-horizonship-dev-wus3' `
	-ExistingHorizonDbClusterName 'horizonship-db-6prmjv3zxbvfs' `
	-OpenAiEndpoint 'https://<foundry-resource>.openai.azure.com/'

azd up
```

`azd up`을 실행할 때 `AZURE_PG_PASSWORD` 또는 `AZURE_OPENAI_KEY`가 azd 환경에 없으면
`preup` hook이 infrastructure parameter를 읽기 전에 화면에 표시하지 않는 방식으로 입력받아 저장합니다.
따라서 Bicep parameter prompt에서 입력한 값이 `preprovision` hook으로 전달되지 않는 문제를 피할 수 있습니다.
`azd provision`을 단독으로 실행할 때는 `preup`이 실행되지 않으므로 먼저 설정 스크립트를 실행해야 합니다.

`existing`은 기본적으로 `RUN_DATABASE_SETUP=false`입니다. 기존 schema와 데이터, model registry,
pipeline을 변경하지 않습니다. DB가 아직 초기화되지 않았을 때만 설정 명령에 `-RunDatabaseSetup`을 추가합니다.
이 옵션은 전체 setup을 실행하므로 기존 샘플 값과 인덱스·pipeline도 갱신합니다. 모델 별칭만 추가할 때는
[루트 README의 `--models-only` 절차](../README.md#모델-호출-위치-선택)를 사용합니다.

### 새 HorizonDB 생성

새 환경에서는 `create`를 지정합니다. DB 관리자 비밀번호는 새 cluster와 backend가 함께 사용합니다.

```powershell
./azd-hooks/configure.ps1 `
	-EnvironmentName demo-new `
	-SubscriptionId 'b214e225-c96c-489e-a778-a1f25bd40cdb' `
	-HorizonDbMode create `
	-ResourceGroupName 'rg-horizonship-demo-new-wus3' `
	-OpenAiEndpoint 'https://<foundry-resource>.openai.azure.com/'

azd up
```

`create`는 새 HorizonDB와 parameter group을 만든 뒤 parameter group이 `InSync`인지 확인합니다.
최초 backend revision이 schema, 샘플 24건, 임베딩, DiskANN index와 변경 감지 pipeline을 준비합니다.
health 검사가 성공하면 setup 플래그를 끄는 새 revision을 만들어 이후 재시작에서는 setup을 반복하지 않습니다.
같은 azd 환경으로 다시 `azd up`을 실행하면 cluster가 있음을 확인하고 `Update` 모드로 전환합니다.

### 방화벽과 종료

Container Apps에서 public HorizonDB endpoint에 연결할 수 있도록 기본값은 Azure 서비스 허용 규칙
`0.0.0.0`을 추가합니다. Azure의 임의 인터넷 주소를 허용한다는 뜻은 아니지만 구독의 모든 Azure
서비스로 제한되는 규칙도 아닙니다. 단기 데모에만 사용하고 운영 환경에서는 VNet 또는 고정 outbound IP로 바꿉니다.
이미 별도 네트워크 경로를 구성했다면 설정 명령에 `-DoNotAllowAzureServices`를 추가합니다.

```powershell
azd down --purge
```

`existing`에서는 종료 전에 azd가 추가한 임시 방화벽 규칙을 제거하고 앱 리소스 그룹을 삭제합니다.
기존 HorizonDB와 데이터는 삭제하지 않습니다. `create`에서는 HorizonDB가 앱과 같은 리소스 그룹에 있으므로
`azd down --purge`가 DB도 함께 삭제합니다. 중간 실패 후 정리할 때는 방화벽 규칙과 남은 리소스를 Portal에서 확인합니다.
기존 DB를 보호하기 위해 `existing` 모드에서는 앱 리소스 그룹과 HorizonDB 리소스 그룹을 같게 설정할 수 없습니다.

azd 환경 값은 로컬 `.azure` 폴더에 저장되고 Git에서 제외됩니다. 비밀번호와 key를 채팅, 로그,
명령 예제에 넣지 마세요. 데모가 끝나면 Azure 리소스를 내린 뒤 `azd env remove demo`로 로컬 환경도 제거합니다.

### 배포 후 검사

`postdeploy` hook은 public frontend의 `/api/health`를 호출해 HorizonDB 연결, Agent Framework,
배송·임베딩 개수와 SQ4 DiskANN 설정을 확인합니다. 성공하면 frontend URL을 출력합니다.
이 검사는 실제 모델 추론을 호출하지 않으므로 배포 후 검색과 대화도 별도로 확인해야 합니다.
Docker Desktop 없이도 ACR remote build를 사용하므로 로컬 Docker daemon은 필수가 아닙니다.

배포 환경은 `CAPTURE_QUERY_PLAN=true`를 기본으로 사용합니다. 검색할 때 backend가
`EXPLAIN (FORMAT JSON, COSTS TRUE)`로 예상 실행 계획을 수집하며 화면의 실행 내역에서 확인할 수 있습니다.
운영 환경에서 추가 DB 호출을 원하지 않으면 `azd env set CAPTURE_QUERY_PLAN false` 후 다시 배포합니다.

2026-09-10 구독 조회에서 West US 3의 두 모델과 quota를 확인했습니다.
West US 2에서는 대상 모델이 목록에 없어 이 스크립트는 West US 3만 허용합니다.
DB 스크립트는 HorizonDB API 지원만 검사합니다. Foundry 스크립트는 모델의 고정 버전, SKU와 남은 quota를 검사합니다.
모델 사용 가능 여부와 용량은 바뀔 수 있으며 조회 성공이 실제 생성 성공을 보장하지는 않습니다.

## 보안과 비용

기존 `deploy.ps1` 흐름은 HorizonDB의 공용 endpoint를 활성화하지만, DB 방화벽에는 자동 조회하거나 직접
지정한 공인 IPv4 하나만 허용합니다. 이 흐름은 `0.0.0.0` 규칙이나 모든 Azure 서비스 허용 규칙을 생성하지 않습니다.
Container Apps용 `azd` 흐름의 임시 Azure 서비스 허용 규칙은 앞의 별도 안내를 따릅니다.
`WhatIf`와 `Deploy`에서 `-ClientIpAddress`를 생략하면 `https://api4.ipify.org`로 공인 IPv4를 조회합니다.
15초 제한으로 조회하고, 실패하거나 올바른 공인 IPv4가 아니면 중단합니다. `Check`와 `Register`는 IP를 조회하지 않습니다.
프록시나 VPN 환경에서는 HTTP 조회 IP와 PostgreSQL 접속 IP가 다를 수 있습니다.
이때는 회사 네트워크의 DB 접속용 공인 egress IP를 `-ClientIpAddress`로 직접 지정합니다.
직접 지정하면 외부 IP 조회를 생략하며, 조회한 IP는 배포 전에 화면에 표시됩니다.

새 Foundry는 백엔드가 호출할 수 있도록 공용 API 접근을 허용하되,
`disableLocalAuth: true`로 키 인증을 차단합니다. 모델 호출에는 Entra ID와 RBAC가 필요합니다.
인터넷에서 접근 가능한 인증 필수 API이며, DB의 IPv4 방화벽 규칙이 Foundry에도 적용되는 것은 아닙니다.
Private Endpoint와 사설 DNS가 필요한 운영 환경에는 이 구성을 그대로 사용하지 마세요.
Global Standard는 추론 처리 위치가 West US 3에 고정되지 않습니다.
`-ModelSku DataZoneStandard`로 변경할 수 있지만 미국 데이터 영역 내 처리와 단일 리전 처리는 다릅니다.

DB 비밀번호는 터미널의 보안 입력으로 받고 Bicep의 `@secure()` 매개변수로 전달합니다.
명령행 인수, 매개변수 파일, 배포 출력에 비밀번호를 넣지 않습니다. 실행 중에는 자식 Bicep 프로세스에
전달할 환경 변수에 평문이 존재하며 `finally`에서 원래 값으로 복원합니다.
프로세스 메모리를 읽을 수 있는 사용자로부터 비밀을 보호하는 방식은 아니므로 신뢰하는 로컬 환경에서 실행합니다.
비밀번호를 환경 변수에 설정한 상태로 `build-params --stdout`, 디버그 로그, 프로세스 덤프를 실행하지 마세요.
Foundry API 키는 스크립트가 조회하거나 출력하지 않습니다.

등록만으로 이 템플릿의 유료 리소스가 만들어지지는 않습니다. `Deploy`는 유료 서비스를 생성합니다.
중간에 실패해도 성공한 리소스는 남아 비용이 발생할 수 있으며 자동 삭제하지 않습니다.
기존 구독이나 리소스 그룹의 정책, RBAC, 배포 시점 용량 때문에 생성이 실패할 수 있습니다.

## 준비

PowerShell 7.4 이상과 Azure CLI가 필요합니다. Windows 기본 Windows PowerShell 5.1 대신
VS Code 터미널에서 `pwsh`를 사용합니다. Azure Public Cloud를 대상으로 작성했습니다.
Azure CLI에는 이미 로그인되어 있다고 가정합니다. 스크립트는 `az login`을 실행하지 않으며,
로그인 정보를 읽지 못하면 안내 메시지와 함께 중단합니다.

```powershell
pwsh --version
az version
az account show --query "{name:name,id:id}" --output table
az bicep install
```

구독 범위 배포, 리소스 그룹 생성, Provider 등록 권한이 필요합니다.
DB 배포에는 Foundry 권한이나 모델 quota가 필요하지 않습니다. Foundry 배포에서 호출자 RBAC도 설정할 때만
Foundry 범위의 `Microsoft.Authorization/roleAssignments/write` 권한이 추가로 필요합니다.
Owner 또는 리소스 배포용 Contributor와 Role Based Access Control Administrator 등의 조합을 사용합니다.
Contributor만으로는 역할을 할당할 수 없으며, 역할 할당 조건이나 조직 정책에 제한이 있으면 관리자에게 확인합니다.
HorizonDB는 Preview이므로 별도 승인이 필요하면 스크립트로 우회할 수 없습니다.

아래 명령은 저장소 최상위 폴더에서 실행합니다. 구독 ID를 생략하면 현재 Azure CLI 구독을 사용하고,
그 ID를 이후 모든 Azure 요청에 명시합니다. CLI의 기본 구독은 변경하지 않습니다.
다른 구독을 사용하려면 해당 실행에 `-SubscriptionId`를 지정합니다.

```powershell
./infra/deploy.ps1 -Mode Check -SubscriptionId 'b214e225-c96c-489e-a778-a1f25bd40cdb'
```

실제 리소스를 만들기 전에 출력되는 구독 이름과 ID를 확인합니다.

## 1. 사전 조회

```powershell
./infra/deploy.ps1 -Mode Check
```

로그인, 구독, HorizonDB 등록 상태와 리전·API 지원을 조회합니다. Foundry나 모델 quota는 조회하지 않습니다.
HorizonDB 등록이 안 되어 있으면 조회 결과를 표시한 뒤 오류로 종료합니다. 이 모드는 등록이나 리소스 생성을 하지 않습니다.

## 2. HorizonDB 등록

```powershell
./infra/deploy.ps1 -Mode Register
```

변경 대상은 `Microsoft.HorizonDB` Provider 하나입니다.
확인 질문에 `REGISTER`를 입력하면 미등록 Provider만 등록하고 CLI의 `--wait`로 완료를 기다립니다.
Portal의 구독 > 리소스 공급자에서 등록해도 됩니다. 이미 `Registered`이면 이 단계는 생략합니다.

`publicpreview`와 `westus3` 기능의 별도 등록이 필수라는 근거는 확인되지 않았으므로,
스크립트는 이 기능들을 요청하거나 배포 선행 조건으로 검사하지 않습니다.
이전 스크립트로 요청한 `publicpreview`가 `Pending`이어도 그 상태만으로 중단하지 않습니다.
기존 기능 요청을 취소하거나 변경하지도 않습니다. 실제 서비스가 추가 승인을 요구하면
Azure what-if 또는 배포 오류에 표시된 조건을 확인하고 구독 관리자나 Azure 지원에 문의합니다.

등록 후 `Check`를 다시 실행합니다. `Deploy`는 Provider를 자동 등록하지 않습니다.

## 3. 변경 내용 확인

현재 구독과 자동 조회한 공인 IPv4를 사용합니다. 별도의 `$clientIp` 입력은 필요하지 않습니다.

```powershell
./infra/deploy.ps1 -Mode WhatIf
```

DB 관리자 비밀번호를 보안 입력 창에 입력합니다. 8~128자이며 영문 대·소문자, 숫자, 특수문자를 포함해야 합니다.
`WhatIf`는 구독 범위 변경을 확인하므로 리소스 그룹이 없어도 먼저 생성하지 않습니다.
Bicep 컴파일과 Azure what-if 성공은 서비스의 실제 배포 성공이나 DB 연결 성공을 보장하지 않습니다.

## 4. 배포

```powershell
./infra/deploy.ps1 -Mode Deploy
```

대상 리소스 그룹 이름으로 첫 확인을 한 뒤 DB 비밀번호를 입력합니다.
스크립트가 what-if를 다시 실행합니다. 결과를 검토한 뒤 Enter를 누르면 기본값 `DEPLOY`로 실제 배포를 시작합니다.
`DEPLOY`를 직접 입력해도 진행하며, `CANCEL` 등 다른 값을 입력하면 취소합니다.
동일 구독에서 같은 스크립트를 동시에 실행하지 마세요. DB 구독 배포 이름은 `horizonship-db`입니다.

리소스 이름은 prefix와 리소스 그룹 ID를 바탕으로 결정됩니다.
성공하면 DB 호스트와 관리자 이름을 출력합니다. Foundry는 생성하거나 변경하지 않습니다.
비밀번호와 API 키는 포함하지 않습니다.

기존 클러스터를 갱신할 때는 **같은 리소스 그룹과 prefix**를 사용하고 `-UpdateExistingCluster`를 추가합니다.
비밀번호도 기존 값을 입력합니다. 값이 다르면 비밀번호가 변경될 수 있습니다.

```powershell
./infra/deploy.ps1 -Mode WhatIf -UpdateExistingCluster
./infra/deploy.ps1 -Mode Deploy -UpdateExistingCluster
```

실패 후 일부 리소스만 존재한다면 Portal에서 클러스터 생성 여부를 확인해 갱신 옵션을 선택합니다.
리소스 이름이나 prefix를 바꾸면 기존 리소스를 교체하지 않고 새로운 리소스가 생성될 수 있습니다.

## Foundry 선택 배포

기존 Foundry의 채팅·임베딩 모델을 사용할 때는 이 단계를 생략합니다. 특히 외부 key 인증 리소스에는
이 템플릿을 적용하지 않습니다. 템플릿은 `disableLocalAuth: true`를 강제합니다.

```powershell
./infra/deploy-foundry.ps1 -Mode Check
./infra/deploy-foundry.ps1 -Mode Register
./infra/deploy-foundry.ps1 -Mode WhatIf
./infra/deploy-foundry.ps1 -Mode Deploy
```

등록이 이미 완료됐다면 `Register`는 생략합니다. 등록 대상은 `Microsoft.CognitiveServices` 하나입니다.
Foundry 스크립트에는 DB 비밀번호 입력, IP 조회, DB 등록 검사, DB 변경이 없습니다.
`WhatIf`는 조회만 수행하고, `Deploy`는 리소스 그룹 이름 확인과 what-if 검토 후 최종 승인을 받습니다.
구독 배포 이름은 `horizonship-foundry`이며 DB 배포 이름과 다릅니다.
성공하면 Foundry 이름, OpenAI endpoint, 두 모델의 deployment 이름을 출력하며 key는 조회하거나 출력하지 않습니다.

호출자 권한은 기본으로 할당하지 않습니다. 백엔드 사용자의 object ID를 지정하면 부모 Foundry 범위에
`Cognitive Services OpenAI User`를 함께 할당할 수 있습니다. 예를 들어 로컬 로그인 사용자를 호출자로 지정합니다.

```powershell
$callerObjectId = az ad signed-in-user show --query id --output tsv
./infra/deploy-foundry.ps1 -Mode WhatIf -ModelCallerPrincipalId $callerObjectId
./infra/deploy-foundry.ps1 -Mode Deploy -ModelCallerPrincipalId $callerObjectId
```

백엔드의 Managed Identity 또는 서비스 주체에는 해당 object ID와 `-ModelCallerPrincipalType ServicePrincipal`을
지정합니다. application/client ID가 아닙니다. RBAC를 생략하면 관리자가 호출 권한을 별도로 준비해야 합니다.
새 Foundry는 API key를 비운 backend 호출에 사용할 수 있습니다. 다만 `disableLocalAuth: true`이므로
현재 `azure_ai 2.2.2`의 BYOM pipeline에는 등록할 수 없습니다. DB pipeline을 함께 사용하려면
key 인증을 허용하는 기존 Foundry를 별도로 준비해야 합니다.

`-ModelSku`, `-ChatCapacity`, `-EmbeddingCapacity`는 Foundry 스크립트에서만 받습니다.
사전 quota 검사는 요청한 전체 capacity만큼 미할당 quota가 있어야 통과하는 보수적인 방식입니다.
기존 deployment의 할당량을 차감하지 않으므로 갱신 시 추가 quota가 필요 없어도 중단될 수 있습니다.

같은 리소스 그룹과 prefix를 사용하면 기존 리소스 이름을 유지합니다. 두 스크립트는 서로의 서비스 리소스를
삭제하는 작업을 하지 않습니다. 기존 클러스터를 갱신할 때는 what-if에서 Identity 등 기존 속성 변화도 확인합니다.

## 이전 DB Identity 구성

[configure-db-identity.ps1](configure-db-identity.ps1)과 [foundry-model-access.bicep](foundry-model-access.bicep)은
Managed Identity 기반 DB 모델 호출을 검토할 때 쓰던 보조 파일이며 현재 앱의 필수 단계가 아닙니다.
2026-09-10 검증에서 `azure_ai` 2.2.2의 BYOM 등록은 Managed Identity 인증 미지원 오류를 반환했습니다.
DB Identity와 RBAC만 추가해 이 제한을 해결할 수 있다고 가정하지 않습니다.
현재 앱은 DB model registry에 subscription key를 등록합니다.
기존 Identity·RBAC·모델 등록은 자동 삭제하지 않습니다. 다른 용도를 확인한 뒤 별도로 정리합니다.

## 기존 Foundry에 Project만 추가

이미 Foundry를 배포했다면 [foundry-project.bicep](foundry-project.bicep)을 별도로 실행합니다.
이 템플릿은 기존 Foundry를 `existing`으로 참조하고 System Assigned Identity가 있는 project 하나만 생성합니다.
Foundry에 project management가 활성화되어 있어야 하며, `location`은 부모 Foundry와 같아야 합니다.
아래 명령은 현재 배포된 리소스를 대상으로 하며 저장소 최상위 폴더에서 실행합니다.

먼저 변경 내용을 확인합니다.

```powershell
az deployment group what-if `
	--subscription b214e225-c96c-489e-a778-a1f25bd40cdb `
	--resource-group rg-horizonship-dev-wus3 `
	--name horizonship-foundry-project `
	--mode Incremental `
	--template-file infra/foundry-project.bicep `
	--parameters foundryName=horizonship-ai-6prmjv3zxbvfs projectName=horizonship location=westus3
```

2026-09-10에 이 명령의 what-if가 성공했습니다. 결과는 `1 to create, 3 to ignore`이며,
생성 대상은 `horizonship` project입니다. 기존 Foundry, HorizonDB, parameter group은 변경 대상에서 제외됩니다.
Project의 실제 생성은 아직 실행하지 않았으며, what-if 성공이 실제 생성 성공을 보장하지는 않습니다.

Project만 실제로 생성하려면 다음 명령을 실행합니다. 이 명령은 별도 확인 질문 없이 배포를 시작합니다.

```powershell
az deployment group create `
	--subscription b214e225-c96c-489e-a778-a1f25bd40cdb `
	--resource-group rg-horizonship-dev-wus3 `
	--name horizonship-foundry-project `
	--mode Incremental `
	--template-file infra/foundry-project.bicep `
	--parameters foundryName=horizonship-ai-6prmjv3zxbvfs projectName=horizonship location=westus3 `
	--query properties.outputs --output json
```

`Incremental` 모드를 유지합니다. 이 배포에는 DB 비밀번호, IP 조회, 모델 재배포,
`-UpdateExistingCluster` 옵션이 필요하지 않습니다. 사용자에 대한 RBAC 할당은 포함하지 않으므로,
project가 포털에 보이지 않으면 로그인 계정과 접근 권한을 확인합니다.

Project는 부모 Foundry의 기존 모델 deployment를 공유합니다. 백엔드는 기존 Azure OpenAI endpoint를
계속 사용하며, `AZURE_OPENAI_ENDPOINT`를 project endpoint로 바꾸지 않습니다.

## 5. 백엔드 연결

기존 [backend 설정 예제](../backend/.env.example)를 참고해 백엔드의 `.env`에 배포 출력을 입력합니다.
`AZURE_PG_NAME`은 이 샘플에서 클러스터의 기본 DB인 `postgres`를 사용합니다.
앱 데이터는 그 안의 `horizon_ship` 스키마에 생성됩니다. 별도 애플리케이션 DB가 필요하면 SQL로 생성한 뒤 값을 바꿉니다.

| 환경 변수 | 입력 값 |
| --- | --- |
| `AZURE_PG_HOST` | 출력의 `databaseHost` |
| `AZURE_PG_NAME` | `postgres` |
| `AZURE_PG_USER` | 출력의 `databaseUser` |
| `AZURE_PG_PASSWORD` | 배포 시 입력한 비밀번호 |
| `AZURE_OPENAI_ENDPOINT` | 출력의 `openAiEndpoint` |
| `AZURE_OPENAI_KEY` | key 인증을 허용하는 외부 리소스의 subscription key. DB pipeline 구성에 필수입니다. |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5.4` |
| `AZURE_EMBED_DEPLOYMENT` | `text-embedding-3-small` |

기존 설정 파일을 덮어쓰지 말고 필요한 값만 수정합니다. 키를 채팅이나 Git에 넣지 마세요.
스크립트는 기존 로컬 설정 파일을 변경하지 않습니다.

key가 있으면 backend 호출과 DB pipeline 모두 key 인증을 사용합니다. 인증 실패 시 다른 방식으로 자동 전환하지 않습니다.
setup은 key를 DB model registry에 저장하므로 DB와 백업의 접근 권한을 비밀정보 관리 기준에 맞춰 제한해야 합니다.
key를 setup 출력, 채팅, Git에 넣지 마세요.
DB 사용자 이름과 비밀번호는 그대로 필요하며, 키 인증을 다시 허용하도록 Azure 정책을 바꾸지는 않습니다.

```powershell
Set-Location backend
uv run python -m app.setup_database
uv run python -m app.server
```

Bicep은 `azure.extensions` 허용 목록과 parameter group 연결까지만 처리합니다.
확장 설치, 테이블, 샘플 데이터, 백엔드 임베딩 생성과 DiskANN 인덱스 구성은
기존 [setup_database.py](../backend/app/setup_database.py)가 수행합니다.
설정 적용 지연이나 확장 지원 오류가 나면 HorizonDB parameter group의 동기화 상태와 허용 확장을 확인합니다.

## 검증과 제한

```powershell
./infra/Test-Deployment.ps1
./infra/Test-Deployment.ps1 -CompileTemplates
```

로컬 테스트는 Azure CLI, IP 조회, 보안 입력을 대체해 기본 구독 선택, 자동 IPv4 조회와 실패 처리,
페이지 처리, Provider 등록과 반복 실행, quota 부족, 방화벽 입력,
what-if 실패, 배포 취소, 환경 변수 복원과 DB·Foundry 배포 범위 분리를 검사합니다. 실제 리소스를 생성하지 않습니다.
`-CompileTemplates`는 로컬 Azure CLI와 Bicep이 필요합니다. 가짜 설정으로 두 parameter 파일을 컴파일하고
ARM 템플릿의 리소스 분리·모델 개수·key 인증 차단을 검사합니다. Azure 리소스 작업이나 로그인은 실행하지 않습니다.

HorizonDB의 `2026-05-01-preview` 타입이 로컬 Bicep 타입 카탈로그에 없으면 `BCP081` 경고가 발생합니다.
공식 REST 규격을 기준으로 작성했으며 경고를 숨기지 않습니다. 컴파일은 가능하지만 HorizonDB 속성은
로컬 타입 검사를 받지 못하므로 Azure what-if와 실제 배포 검증이 필요합니다.
현재 클라우드 배포 및 실제 모델 호출은 검증하지 않았습니다.

에디터에서 [main.bicepparam](main.bicepparam)이나 [foundry.bicepparam](foundry.bicepparam)을 단독으로 열면
환경 변수 누락 오류가 표시될 수 있습니다. 각 스크립트가 실행 중에만 환경 변수를 주입하므로 예상된 표시입니다.
기본 비밀번호를 파일에 추가하지 말고 스크립트로 실행합니다. 실행 환경 변수를 전달한 CLI 컴파일은 검증했습니다.

## 참고 자료

- [HorizonDB 클러스터 API](https://learn.microsoft.com/en-us/rest/api/horizondb/clusters/create-or-update)
- [HorizonDB Managed Identity와 갱신 API](https://learn.microsoft.com/en-us/rest/api/horizondb/clusters/update)
- [HorizonDB 방화벽 API](https://learn.microsoft.com/en-us/rest/api/horizondb/firewall-rules/create-or-update)
- [HorizonDB parameter group API](https://learn.microsoft.com/en-us/rest/api/horizondb/parameter-groups/create-or-update)
- [HorizonDB 확장 허용](https://learn.microsoft.com/en-us/azure/horizondb/extensions/how-to-allow-extensions)
- [HorizonDB 지원 리전](https://learn.microsoft.com/en-us/azure/horizondb/overview#azure-regions)