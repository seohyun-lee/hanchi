# Hanchi (한치)

> 한국어 검색어의 단어별 역할과 가중치를 문맥으로 판단합니다. 한치 앞을 모를 땐 단정하지 않고 가능성을 남깁니다.

[English](README.en.md)

Hanchi(한치)는 형태소 분석기(Kiwi) 위에서 동작하는 검색어 분석 레이어입니다. 문서 전체를 품사 색인하는 도구가 아니라, 검색엔진·음성 비서에 들어오는 짧은 사용자 입력어의 단어별 역할(개체, 범주, 지역, 조건, 명령 등)과 가중치를 문맥으로 판단해 검색 품질을 높이는 것이 목적입니다. 검색 자체는 하지 않으며, 해석이 모호하면 하나로 단정하지 않고 가능한 해석과 확률을 함께 넘겨줍니다.

이름은 "한글 + 가중치"에서 왔습니다.

> **상태:** 개발 초기(pre-alpha)입니다. 아래 API·CLI는 목표 설계이며 마일스톤별로 구현 중입니다.

## 설치

```bash
pip install hanchi          # 아직 PyPI에 배포되지 않았습니다. 지금은 소스에서 설치하세요.
pip install -e ".[dev]"     # 개발용
```

Python 3.10 이상이 필요합니다.

## 사용 예

```python
from hanchi import Analyzer

a = Analyzer(plugins=["preset:local"])  # 패키지 기본값 + 장소 검색 프리셋
r = a.analyze("지금 영업중인 식당 찾아줘")
for s in r.spans:
    print(s.text, s.top.role, round(s.top.p, 2), s.top.weight, s.attach)
# 지금   CONSTRAINT 0.92 ... {'type': 'time', 'anchor': 'now'}
# 영업중 CONSTRAINT ...     {'type': 'status', 'anchor': 'now'}
# 인     FUNC ...
# 식당   HEAD ...
# 찾아줘 COMMAND 0.98 ...

r = a.analyze("강남 방탈출 찾아줘 왜 안나와")
r.signals  # [{'type': 'dissatisfaction', 'span': '왜 안나와', 'clause_id': 1}]
r.interpretations  # 분절 해석별 확률 (예: '강남 방탈출'을 한 이름으로 읽는 해석)
a.analyze("나를 찾아줘", explain=True).explain  # 특징별 기여도

ranking = a.rank("강남 카페", ["강남 카페 라떼", "홍대 카페"])  # 검색 결과 후보 재정렬
ranking.names(), ranking.mode  # (['강남 카페 라떼', '홍대 카페'], 'strict')
```

`Span.resolved`는 가장 높은 가설의 확률이 임계값(기본 0.9) 이상일 때만 채워집니다. 그렇지 않으면 `hypotheses`에 남은 모든 해석을 보고 검색 쪽에서 해석별로 시도하면 됩니다.

## 명령줄 (CLI)

```bash
hanchi analyze -p preset:local "주변 강남 방탈출 찾아줘 왜 안나와"   # 표: span | clause | 품사 | 역할(p) | sense/type | weight | attach | 근거
hanchi analyze --json "나를 찾아줘"                                   # JSON
hanchi analyze --context prev.json "강남 방탈출 찾아줘 왜 안나와"      # 세션 문맥 {"prev_query": ..., "prev_result_count": 0}
hanchi analyze -w 4 --json < queries.txt                               # 한 줄에 쿼리 하나, 결과는 JSON lines
hanchi rank "강남 카페" -c candidates.txt                              # 후보 재정렬 + 점수 근거 (후보 줄은 이름 또는 JSON)
hanchi expand "식당"                                                   # 동의어·상하위어 확장
hanchi eval -c my_search/eval.yaml                                     # 평가
hanchi repl                                                            # 대화형 (:help)
hanchi dict export --format kiwi -o out/                               # Kiwi 사용자 사전
hanchi dict export --format nori -o out/                               # Elasticsearch/OpenSearch nori 사용자 사전
```

모든 명령은 `--config 설정.yaml`, `-p 플러그인`(여러 번), `--override overrides.tsv`를 받습니다.
여러 쿼리를 한꺼번에 처리할 때는 파이썬에서 `Analyzer.analyze_batch(texts, workers=4)`를 쓰면 됩니다.

nori 내보내기는 이름(개체·뜻 사전 표기)을 분해형 없이, 여러 명사로 된 범주어(`서비스센터 서비스 센터`)는 분해형과 함께 씁니다. `decompound_mode: mixed`와 함께 쓰는 것을 권장합니다.

## 핵심 개념: 3층 모델

| 층 | 질문 | 값의 형태 | 담당 |
|---|---|---|---|
| 1. 형태 | 문법적으로 무엇인가 | 하나로 정해짐 (`찾/VV + 아/EC + 주/VX + 어/EF`) | 형태소 분석기(Kiwi) |
| 2. 역할 | 이 입력에서 무슨 일을 하나 | 후보 여러 개 + 확률 (`COMMAND 0.97, ENTITY 0.03`) | 후보 생성(사전·규칙) + 문맥 판정 |
| 3. 가중치 | 그 역할이면 얼마나 중요한가 | (단어, 역할, 입력 문맥)의 함수 | weighter |

- 형태는 하나, 역할은 확률 분포, 가중치는 역할과 문맥의 함수입니다.
- 후보 생성은 빠짐없이(재현율), 문맥 판정은 정확하게(정밀도) 합니다.
- 확신이 있을 때만 `resolved`를 채웁니다(기본 임계값 p ≥ 0.9). 모호하면 모든 가설을 남깁니다.

## 역할 체계

| 역할 | 의미 | 예 |
|---|---|---|
| `ENTITY` | 개체 이름(브랜드, 작품 제목, 인물, 상품명, 건물명 등) | 아이폰, 나를 찾아줘 |
| `MODIFIER` | 범주를 좁히는 수식어 | 무선(이어폰), 스포츠(센터) |
| `LOCATION` | 지역·위치 | 강남, 부산 |
| `HEAD` | 범주·유형 | 케이스, 이어폰, 식당, 레시피 |
| `CONSTRAINT` | 조건(시간, 상태, 가격, 거리, 수량) | 지금, 싼, 근처, 2개 |
| `QUALIFIER` | 지점·판·버전 표지 | 2판, 시즌2, (강남)점 |
| `COMMAND` | 요청·명령 표현 | 찾아줘, 알려줘, 보여줘 |
| `META` | 불만·정정 같은 발화 신호 (검색 가중치 0, `signals`로 전달) | 왜 안나와, 아니 그거 말고 |
| `FUNC` | 조사·어미·기호 | 를, 의, ? |

가설의 단위는 (역할, 뜻)입니다. 예를 들어 "배"는 `HEAD/과일`, `HEAD/선박` 등 여러 가설을 가질 수 있습니다.
역할별 기본 가중치는 모두 설정 파일로 바꿀 수 있습니다.

## 판단 원칙

**어떤 단어도 역할을 확정해서 지우지 않습니다.** 후보를 다 만들고, 문맥 증거로 확률을 매기고, 모호하면 해석을 나눠서 넘깁니다. "찾아줘", "안나와", "주변", "애플" 모두 같은 틀로 처리합니다.

개체(ENTITY) 해석의 근거 강도:

1. 개체 이름 **전체 정확 일치** → 강한 근거
2. 개체 이름의 **핵심부(구별력 있는 부분) 일치**, 특히 접두 일치 → 중간~강한 근거
3. 개체 이름의 **흔한 부분(꼬리, 범주어, 기능어)만 일치** → 근거로 보지 않음

## 내 도메인에 맞게 튜닝하기

Hanchi의 도메인 지식(사전, 어휘, 가중치, 임계값, 뜻 사전확률, 핫픽스)은 전부 **플러그인 디렉토리**에 있습니다. 코드를 고치지 않고 플러그인 경로와 설정 파일만 바꿔서 도메인을 갈아끼울 수 있습니다.

### 1. 설정 파일 하나로 시작하기

```yaml
# my_search/hanchi.yaml
plugins:                # 순서대로 적용, 뒤에 올수록 우선
  - preset:local        # 패키지에 들어 있는 예시 프리셋 (web / commerce / local)
  - ./plugin            # 내 도메인 플러그인 (이 파일 기준 상대 경로)
overrides:              # 마지막에 적용되는 핫픽스 (재배포 없이 수정)
  - ./hotfix/overrides.tsv
include_default: true   # 패키지 기본 플러그인 포함 여부
```

```python
from hanchi import Analyzer

a = Analyzer.from_config("my_search/hanchi.yaml")
# 같은 내용: Analyzer(["preset:local", "my_search/plugin"], overrides=["my_search/hotfix/overrides.tsv"])
```

### 2. 덮어쓰기 우선순위

```
overrides (overrides.tsv, overrides=)  >  사용자 플러그인 (뒤에 올수록 우선)  >  프리셋  >  패키지 기본값
```

- YAML(`roles.yaml`, `rules.yaml` 등)은 키 단위로 병합합니다. 바꾼 키만 바뀌고 나머지는 앞 단계 값이 유지됩니다.
- 사전·어휘 파일은 합쳐집니다. 앞 단계 항목을 지우려면 줄 앞에 `-`를 붙입니다(`-센터`).
- `overrides.tsv`는 분석 결과 전체보다 우선합니다.

### 3. 플러그인 디렉토리 구조

모든 파일은 선택입니다. 필요한 것만 두세요. 템플릿: [`examples/plugin_template/`](examples/plugin_template/)

```
plugin/
├─ roles.yaml          # 역할별 기본 가중치
├─ rules.yaml          # resolver 특징 가중치, 임계값(threshold), 해석·가중치·attach 설정
├─ entities/*.tsv      # 개체 사전
├─ lexicon/            # 역할 어휘
│  ├─ head.txt  qualifier.txt  command.txt  location.txt  unit.txt
│  └─ constraint.tsv  meta.tsv
├─ senses.tsv  aliases.tsv  synonyms.tsv  hypernyms.tsv  compat.tsv  sense_prior.tsv
├─ idf.tsv
├─ overrides.tsv
└─ normalize.yaml  patterns.yaml  backend.yaml   # 언어 팩(한국어) 설정
```

### 4. 파일별 포맷

TSV는 탭 구분, `#`으로 시작하는 줄은 주석입니다.

| 파일 | 포맷 | 예 |
|---|---|---|
| `roles.yaml` | `weights: {ROLE: 가중치}` | `weights: {LOCATION: 0.7}` |
| `rules.yaml` | 패키지 기본값(`hanchi/data/default/rules.yaml`)과 같은 구조 | `threshold: 0.85` / `features: {COMMAND: {request_clause_final: 3.5}}` |
| `entities/*.tsv` | `이름 ⇥ 대표형 ⇥ 타입 ⇥ 출처 ⇥ 점수` | `센터필드 ⇥ 센터필드 ⇥ building ⇥ manual ⇥ 1.0` |
| `lexicon/*.txt` | 한 줄에 하나. `re:`로 시작하면 정규식 | `점` / `re:[a-z]점` |
| `lexicon/constraint.tsv` | `어휘 ⇥ 타입`(proximity, time, status, price, quantity …) | `근처 ⇥ proximity` |
| `lexicon/meta.tsv` | `어휘 ⇥ 타입`(dissatisfaction, correction) | `말고 ⇥ correction` |
| `senses.tsv` | `sense_id ⇥ 대표형 ⇥ 역할 ⇥ 타입 ⇥ 메모` | `apple_inc ⇥ 애플 ⇥ ENTITY ⇥ company` |
| `aliases.tsv` | `표기 ⇥ 대상 ⇥ 점수`. 대상은 sense_id, 개체 이름, 또는 다른 비모호 표기 | `스벅 ⇥ 스타벅스` / `센타필드 ⇥ 센터필드` |
| `synonyms.tsv` | `sense_id ⇥ sense_id` (양방향) | `restaurant ⇥ eatery` |
| `hypernyms.tsv` | `하위 sense ⇥ 상위 sense` (방향 있음) | `restaurant ⇥ hot_place` |
| `compat.tsv` | `타입 ⇥ 타입 ⇥ 점수` (음수면 비호환) | `company ⇥ store_word ⇥ 2.0` |
| `sense_prior.tsv` | `표기 ⇥ sense_id ⇥ 사전확률 [⇥ vertical]` | `애플 ⇥ apple_inc ⇥ 0.9 ⇥ web` |
| `idf.tsv` | `토큰 ⇥ idf` | `센터 ⇥ 1.2` |
| `overrides.tsv` | `패턴 ⇥ 동작 ⇥ 값 ⇥ 메모`. 동작: `role`(값 `ROLE` 또는 `ROLE/sense_id`), `keep`(한 span으로 유지), `split`(값: 공백으로 나눈 조각). 패턴이 `re:`로 시작하면 정규식 | `찾아줘 ⇥ role ⇥ ENTITY ⇥ 가게 이름` |

한 표기가 여러 뜻을 가질 수 있습니다(`배` → 과일·선박·신체). 이런 모호한 표기를 거쳐 서로 다른 뜻이 합쳐지는 일은 없으며, 그런 별칭은 경고(`AliasWarning`)와 함께 무시됩니다.

### 5. 예시 프리셋

| 프리셋 | 들어 있는 것 |
|---|---|
| `preset:web` | 콘텐츠 범주어(가사, 레시피, 줄거리 …), 시즌·특별판 표지, HEAD 가중치 0.4 |
| `preset:commerce` | 상품 범주어(케이스, 충전기 …), 배송·가격 조건, MODIFIER 가중치 0.9 |
| `preset:local` | 업종 범주어, 지점 표지(점, 지점, `re:[a-z]점` …), 근접·영업 조건, 소수의 지역명, LOCATION 가중치 0.7 |

프리셋은 출발점일 뿐입니다. 자기 도메인의 플러그인을 뒤에 쌓아 덮어쓰세요. 패키지 기본값 자체는 특정 도메인에 치우치지 않게 범용 어휘만 담고 있습니다.

### 6. 내 평가셋으로 확인하기

평가셋은 레포 밖 어디에 있어도 됩니다. 설정 파일에 플러그인과 케이스 파일을 적고 실행합니다.

```yaml
# my_search/eval.yaml
plugins: [preset:local, ./plugin]
cases: [cases.tsv, cases.jsonl]   # 순위 평가: Hit@1, MRR
roles: [roles.tsv]                # 역할 평가: 정확도
```

```bash
hanchi eval -c my_search/eval.yaml                # 점수와 실패 사례
hanchi eval -c my_search/eval.yaml --min-hit1 0.9 # 기준 미달이면 exit 1 (CI용)
```

| 파일 | 포맷 |
|---|---|
| `cases.tsv` | `쿼리 ⇥ 후보1｜후보2｜… ⇥ 정답(｜로 복수 가능) ⇥ 도메인: 메모` |
| `cases.jsonl` | `{"query", "candidates": [문자열 또는 {"name", "category", "location"}], "expected_top1", "entities": [[이름, 타입]], "plugins": [...], "context": {...}}` |
| `roles.tsv` | `쿼리 ⇥ span ⇥ 기대 역할(ROLE, ROLE/sense_id, none) ⇥ 메모` |

공개 범용 평가셋은 [`eval/`](eval/)에 있습니다.

## 라이선스

- Hanchi: [Apache-2.0](LICENSE). 서드파티 고지는 [NOTICE](NOTICE)를 보세요.
- 형태소 분석기 Kiwi(kiwipiepy)는 **0.24.0부터 Apache-2.0**입니다. 0.23.2 이하는 LGPL이므로 Hanchi는 `kiwipiepy>=0.24.0`을 요구합니다.
- 국립국어원 사전(표준국어대사전·우리말샘, CC BY-SA 2.0 KR) 데이터는 이 저장소와 배포물에 포함하지 않습니다. 선택 기능에서 런타임 조회 결과를 사용자 로컬 캐시에만 저장합니다.
