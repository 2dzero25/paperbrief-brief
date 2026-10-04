# PaperBrief 브리프

최근 공개된 논문 목록에서 한 편을 고르면, 원문 그림과 재현 체크가 들어간 보고서를 만들어 주는 로컬 웹앱을 만든다.

## 왜

논문을 재현하거나 공개 코드를 돌려 보기 전에, 그 논문이 무엇을 했고 재현할 수 있는지를 빠르게 파악하고 싶다. 초록만 줄인 요약으로는 표와 그림 속 결과를 알 수 없다.

## 원하는 동작

**목록**
- 앱을 켜거나 [수집]을 누르면 최근 논문이 들어온다.
- 카드 한 장에 upvotes, 제목, 한 줄 요약, 분야, 코드 유무, 보고서 상태가 보인다.
- 분야와 "코드 있음"으로 거른다.
- 한 줄 요약은 KO/EN 탭으로 바꿔 본다. EN은 HF가 주는 `ai_summary`를 쓰고, 없으면 초록 첫 문장을 쓴다. KO는 LLM으로 만든다.
- 주말·휴일처럼 그날 논문이 없으면 가장 최근 발표일을 보여 준다.
- upvotes는 수집할 때 저장된 최근 3개 발표일치만 새 값으로 갱신한다(달력 3일이 아니다).

**보고서**
- 카드를 누르면 PDF를 받아 파싱하고 보고서를 만든다. 한 번 만들면 저장해 두고 다시 만들지 않는다.
- 순서: 한 문장 훅(핵심 수치 1개) → 원문 그림 1~2장과 캡션 → 방법 / 결과 / 차이 / 의미 → 재현 체크(코드, 가중치, 데이터, GPU, 라이선스) → 한계.
- 논문에 없는 내용은 "명시 없음"으로 쓴다. 본문에 없는 수치는 쓰지 않는다.
- 재현 체크의 판정은 그 논문 자체가 쓰거나 공개한 것만 기준으로 한다. 논문이 인용하거나 검토한 다른 연구(서베이 등)의 코드·GPU는 세지 않는다.
- 그림은 다중 패널을 한 장으로 본다: 캡션이 마지막 패널에만 붙으므로 캡션 없는 바로 앞 이미지 블록을 같은 그림의 패널로 묶어 보여 준다.
- 진행 중, 완료, 실패 상태가 보이고, 실패하면 실패한 단계부터 다시 시도한다.

**질문**
- 보고서 아래에서 그 논문에 대해 질문한다. 질문과 답은 저장된다.

**화면 문구:** 라벨은 1~2단어로 쓴다. 설명 문장은 넣지 않는다. 상태는 기호와 색으로 보여 준다. 화면 참고: `wireframe.html`.

## 정해진 것

| 항목 | 내용 |
|---|---|
| 실행 환경 | Windows 또는 Ubuntu + NVIDIA GPU 16GB 한 장. 개인 PC 로컬 전용, 로그인 없음, `127.0.0.1`만 연다 |
| 실행 방법 | `run.bat`(Windows) / `run.sh`(Linux) 더블클릭 → 서버 시작 → 기본 브라우저 자동 열림. 데스크톱 앱 패키징(Electron 등)은 하지 않는다 |
| 스택 | Python 3.12 + uv, FastAPI, 정적 HTML 1장 + vanilla JS, `sqlite3`, `httpx`, `openai` SDK |
| 테스트 | `uv run pytest`, 타입체크 `uv run pyright`. 네트워크가 필요한 테스트는 저장해 둔 응답(fixture)으로 돈다 |
| 논문 목록 | Hugging Face Daily Papers API `GET https://huggingface.co/api/daily_papers?limit=100`. `limit`을 빼면 50건만 온다. `date`를 생략하면 가장 최근 발표일부터 최신순으로 여러 날이 섞여 오고 `Link rel=next`가 항상 붙으므로, 첫 항목과 다른 날짜가 나오는 페이지에서 멈춘다. 주말에도 `date` 생략 호출은 직전 발표일을 돌려준다. 특정 날짜를 받는 `date=YYYY-MM-DD`는 갱신에만 쓰고, 최신 발표일보다 뒤의 날짜는 400이다(주말 날짜는 0건) |
| 분야 | arXiv API를 그날 받은 ID로 한 번 조회해(`id_list=`) 카테고리만 붙인다. 앱이 직접 분류하지 않는다. RSS는 쓰지 않는다. arXiv 요청은 3초에 1회 이하 |
| PDF | `https://arxiv.org/pdf/<id>`에서 받아 로컬에만 저장한다. 재배포하지 않는다 |
| 문서 파싱 | MinerU `mineru[full]>=4.0.10,<4.1`. 레이아웃 검출 + 1.2B VLM. 파싱 모델은 7B 이하(HF 파라미터 수 기준)여야 하고, 16GB GPU 한 장에서 돌아야 한다. 실측(RTX 5070 Ti, 32~78쪽 논문)은 최대 VRAM 11~13.2GB라 여유가 약 3GB뿐이므로 다른 GPU 프로그램과 동시에 실행하지 않는다 |
| MinerU 호출 | `mineru-kit parse <pdf> -o <dir> -f zip --tier standard`. 실패하면 `--tier basic`(CPU)으로 다시 시도한다. `-f zip`이어야 그림이 `images/`에 파일로 나온다. `mineru parse`는 서버가 필요하고 앞 10쪽만 파싱하므로 쓰지 않는다 |
| MinerU 출력 | `markdown.md`, `structured_content.json`(블록 type, bbox, 캡션), `images/page_{쪽}_{image\|chart\|table\|equation}_{n}.jpg`. `Figure`라는 블록 타입은 없다. 그림 후보는 type이 `image` 또는 `chart`이고 캡션이 `Figure`로 시작하며 이미지 파일이 실제로 있는 블록이다(`chart`에는 가짜 캡션이 앞에 붙기도 하고 표에도 `image_source`가 있다). 다중 패널 그림은 캡션이 마지막 패널에만 붙는다 |
| MinerU 모델 | HF 토큰이 필요 없다. 첫 파싱 때 `~/.mineru/models`로 자동으로 받는다(standard 약 3GB). VLM 엔진은 OS마다 다르다: Windows는 LMDeploy, Linux는 vLLM(`mineru[full]`이 OS별로 골라 설치한다) |
| torch와 lock | Windows의 PyPI torch는 CPU 전용이라 `pyproject.toml`에서 torch·torchvision을 직접 의존성으로 두고 Windows만 PyTorch cu128 인덱스로 받는다. `lmdeploy`의 Linux 휠 메타데이터가 `nvidia-nccl-cu12`를 요구해 Windows lock이 깨지므로 `override-dependencies`로 Linux 전용으로 묶는다. 이 두 설정이 있으면 Windows·Linux x86_64·Linux aarch64 lock이 함께 풀린다 |
| LLM | OpenAI Responses API `client.responses.parse(..., text_format=<Pydantic 모델>)`. 보고서·질문은 `gpt-6.1-sol`, 한 줄 요약은 `gpt-6-luna`. 보고서 한 편은 입력 3.4만~7만 토큰(실측 약 $0.07~0.14) |
| 설정 | `.env.example`을 `.env`로 복사해서 쓴다. `.env`는 커밋하지 않는다 |
| 데이터 위치 | repo 밖. Windows `%LOCALAPPDATA%\PaperBrief`, Linux `~/.local/share/PaperBrief` |
| 외부 전송 | 보고서·질문을 만들 때 논문 본문이 OpenAI API로 나간다. 화면 맨 아래에 작게 표시한다 |
| 쓰지 않는 것 | HF 응답의 `thumbnail`(PDF 첫 쪽 렌더라 저자 이메일이 보인다) |

## 개발 환경

repo에 아래 설정을 둔다.

**`.mcp.json`**: 코드를 쓰기 전에 현재 문서를 확인하고, 코드가 생긴 뒤 심볼 단위로 탐색할 수 있게 MCP 서버를 둔다.
- Context7: 라이브러리 문서(FastAPI, httpx, pydantic, pytest)
- DeepWiki: GitHub 저장소 질의(`opendatalab/MinerU`)
- mcpdoc: llms.txt 문서(OpenAI, uv)
- Serena: 심볼 탐색. 시작할 때 브라우저 대시보드를 열지 않는다
- 각 도구의 설치·연결 방법은 그 도구의 현재 공식 문서를 따른다

**`AGENTS.md`**: Claude와 Codex가 함께 읽는 지침. 아래가 들어가야 한다.
- 설치·테스트·타입체크·실행 명령
- 어떤 대상의 문서를 어떤 MCP로 확인하는지
- 코드 탐색은 Serena 또는 LSP를 grep보다 먼저 쓴다는 규칙
- Windows와 Ubuntu에서 모두 도는 코드 규칙
- `## Code Review Rules`: Codex 리뷰어가 볼 규칙 2~3개(비밀값 하드코딩, 기존 DB 행을 지우는 스키마 변경, 7B 초과 파싱 모델)

**`CLAUDE.md`**: `AGENTS.md`를 불러오는 한 줄.

**Python LSP**: Claude Code 플러그인으로 pyright를 붙인다.

**spec**: `/to-spec`으로 GitHub 이슈에 남긴다. 로컬 `spec.md` 파일은 따로 만들지 않는다.

**구현**: `/implement-spec`을 돌릴 때 draft PR을 열어 달라고 한다. 티켓이 모두 통합 브랜치에 merge되면 PR을 ready로 바꾼다. ready로 바꾸면 Codex가 리뷰하고, 리뷰 반영은 repo에 들어 있는 `codex-pr-review` 스킬이 맡는다. merge는 사람이 한다.

**Codex 리뷰 수신**: `gh extension install cli/gh-webhook`을 설치해 둔다. `codex-pr-review` 스킬이 리뷰 도착을 webhook으로 바로 받는다. 설치되지 않았으면 30초 폴링으로 동작한다.

## 용어

`/grill-with-docs`가 `GLOSSARY.md`를 만들 때 이 정의에서 시작한다.

| 용어 | 뜻 |
|---|---|
| 발표일 | HF Daily Papers에 논문이 올라온 날짜. 앱의 모든 날짜는 이것이다 |
| 카드 | 목록에서 논문 한 편을 보여 주는 칸 |
| 보고서 | 논문 한 편에 대해 한 번 만들어 저장하는 글. 훅, 그림, 방법·결과·차이·의미, 재현 체크, 한계로 이뤄진다 |
| 재현 체크 | 코드, 가중치, 데이터, GPU, 라이선스 5항목을 논문 근거로 적은 표 |
| 그림 후보 | MinerU가 뽑은 그림 중 캡션이 `Figure`로 시작하는 것. LLM이 이 중 1~2장을 고른다 |
| 파싱 | MinerU로 PDF를 markdown·그림 파일로 바꾸는 단계 |

## 범위 밖

로그인, 여러 사용자, 클라우드 배포, 설치 파일 패키징, 알림, 상주 스케줄러, 개인화 추천, PDF 직접 업로드.
