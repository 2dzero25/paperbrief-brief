# PaperBrief 브리프

최근 공개된 논문 목록에서 한 편을 고르면, 원문 그림과 재현 체크가 들어간 보고서를 만들어 주는 로컬 웹앱을 만든다.

## 왜

논문을 재현하거나 공개 코드를 돌려 보기 전에, 그 논문이 무엇을 했고 재현할 수 있는지를 빠르게 파악하고 싶다. 초록만 줄인 요약으로는 표와 그림 속 결과를 알 수 없다.

## 원하는 동작

**목록**
- 앱을 켜거나 [수집]을 누르면 최근 논문이 들어온다.
- 카드 한 장에 upvotes, 제목, 한 줄 요약, 분야, 코드 유무, 보고서 상태가 보인다. upvotes는 HF `paper.upvotes`, 코드 유무는 `paper.githubRepo`(★는 `githubStars`), 프로젝트 페이지는 `projectPage`, 기관은 `organization`(있을 때만)에서 가져온다.
- 분야와 "코드 있음"으로 거른다.
- 한 줄 요약은 KO/EN 탭으로 바꿔 본다. EN은 HF가 주는 `ai_summary`를 쓰고, 없으면 초록 첫 문장을 쓴다. `ai_summary`는 거의 없어서(2026-10-02 84건 중 1건) 대부분 초록 첫 문장이 된다. KO는 LLM으로 만든다.
- 날짜 기준은 HF Daily 날짜(발표일) 하나다. 목록 그룹, ◀▶ 이동, 보고서 머리의 날짜가 모두 이 날짜다.
- `date`를 빼고 부르면 HF가 최신 발표일 50건을 준다. 최신 발표일보다 뒤의 `date=`는 HF가 400으로 거절하므로, 주말·휴일에는 최신 발표일을 보여 준다.
- 수집할 때 저장된 최근 3개 발표일의 upvotes와 ★만 새 값으로 갱신한다.

**보고서**
- 카드를 누르면 PDF를 받아 파싱하고 보고서를 만든다. 한 번 만들면 저장해 두고 다시 만들지 않는다.
- MinerU가 PDF를 markdown과 그림 파일로 바꾸고, 그림 선택과 문장은 `gpt-6.1-sol`이 맡는다. LLM에는 이미지를 보내지 않고 캡션만 보낸다.
- 순서: 한 문장 훅(핵심 수치 1개) → 원문 그림 1~2장과 캡션 → 방법 / 결과 / 차이 / 의미 → 재현 체크(코드, 가중치, 데이터, GPU, 라이선스) → 한계.
- 논문에 없는 내용은 "명시 없음"으로 쓴다. 본문에 없는 수치는 쓰지 않는다.
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
| 논문 목록 | Hugging Face Daily Papers API `GET https://huggingface.co/api/daily_papers?date=YYYY-MM-DD&limit=100`. `limit`을 빼면 50건만 온다. 100건을 넘으면 `p=`로 다음 쪽을 받는다. 주말에는 0건이다 |
| 분야 | arXiv API를 그날 받은 ID로 한 번 조회해(`id_list=`) 카테고리만 붙인다. `max_results`를 주지 않으면 10건만 오므로 ID 수만큼 지정한다. 앱이 직접 분류하지 않는다. RSS는 쓰지 않는다. arXiv 요청은 3초에 1회 이하 |
| PDF | `https://arxiv.org/pdf/<id>`에서 받아 로컬에만 저장한다. 재배포하지 않는다 |
| 문서 파싱 | MinerU `mineru[full]>=4.0.10,<4.1`. 레이아웃 검출 + 1.2B VLM. 파싱 모델은 7B 이하(HF 파라미터 수 기준)여야 하고, 16GB GPU 한 장에서 돌아야 한다 |
| MinerU 호출 | `mineru-kit parse <pdf> -o <dir> -f zip --tier standard`. 실패하면 `--tier basic`(CPU)으로 다시 시도한다. `-f zip`이면 `-o` 폴더에 `<pdf명>.zip` 하나만 생기고, 앱이 이 zip을 푼다. `mineru parse`는 서버가 필요하고 그림 파일을 내지 않아서 쓰지 않는다(10쪽 제한은 `--pages all`로 풀린다) |
| MinerU 출력 | `markdown.md`, `structured_content.json`(블록 type, bbox, 캡션), `images/` 폴더. 그림 파일명을 조합하지 말고 `structured_content.json`과 `markdown.md`에 적힌 참조 경로를 그대로 따른다(확장자도 jpg로 고정되지 않는다). 그림 캡션은 `Figure`로 시작하는 것을 고른다 |
| MinerU 모델 | HF 토큰이 필요 없다. 첫 파싱 때 `~/.mineru/models`로 자동으로 받는다(standard 약 3.2GB). VLM 엔진은 OS마다 다르다: Windows는 LMDeploy, Linux는 vLLM(`mineru[full]`이 OS별로 골라 설치한다). 16GB GPU에서 standard가 도는지는 아직 실측하지 않았다. 첫 구현 작업이 스모크 테스트다 |
| torch와 lock | Windows의 PyPI torch는 CPU 전용이라 `pyproject.toml`에서 torch·torchvision을 직접 의존성으로 두고 Windows만 PyTorch cu128 인덱스로 받는다. `lmdeploy`의 Linux 휠 메타데이터가 `nvidia-nccl-cu12`를 요구해 Windows lock이 깨지므로 `override-dependencies`로 Linux 전용으로 묶는다. 이 두 설정이 있으면 Windows·Linux x86_64·Linux aarch64 lock이 함께 풀린다 |
| LLM | OpenAI Responses API `client.responses.parse(..., text_format=<Pydantic 모델>)`. 보고서·질문은 `gpt-6.1-sol`, 한 줄 요약은 `gpt-6-luna` |
| 설정 | `.env.example`을 `.env`로 복사해서 쓴다. `.env`는 커밋하지 않는다. `OPENAI_API_KEY`가 없으면 서버가 시작하지 않는다 |
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
