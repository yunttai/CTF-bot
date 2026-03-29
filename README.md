# CTF-bot
CTFtime과 K-CTF 정보를 조회하는 디스코드 봇입니다. 다가오는/진행 중 대회는 리포지토리의 SQLite DB 스냅샷에서 읽고, GitHub Actions는 1시간마다 새 CTF를 Discord 웹훅으로 알릴 수 있습니다.

## 기능
- `/ctf upcoming`: 다가오는 CTF 조회
- `/ctf ongoing`: 진행 중인 CTF 조회
- `/ctf search <keyword>`: CTF 이름 검색
- `/kctf contests`: K-CTF 대회 목록 조회
- `/kctf search <keyword>`: K-CTF 대회 검색
- `/kctf updates`: K-CTF 최근 업데이트 로그 조회
- `/kctf announcement`: K-CTF 최신 공지 조회
- `AUTO_UPDATE_CHANNEL_ID`를 설정하면 1시간마다 자동 갱신 메시지 업데이트

## 사용 기술
- Python 3.11+
- `discord.py`
- `aiohttp`

## 설치
```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

## 환경 변수
`.env.example`을 참고해서 `.env` 파일을 만든 뒤 값을 채웁니다.

```env
DISCORD_WEBHOOK_URL=여기에_디스코드_웹훅_URL
DISCORD_TOKEN=여기에_디스코드_봇_토큰
DISCORD_GUILD_ID=여기에_테스트할_서버_ID_숫자
AUTO_UPDATE_CHANNEL_ID=자동_업데이트를_보낼_채널_ID
CTF_DB_PATH=data/ctf_snapshot.db
CTFTIME_BASE_URL=https://ctftime.org
CTFTIME_FETCH_LIMIT=100
KCTF_BASE_URL=http://k-ctf.org
HTTP_TIMEOUT_SECONDS=10
```

- `DISCORD_WEBHOOK_URL`: GitHub Actions가 새 CTF를 자동 알림할 Discord 웹훅 URL입니다. 웹훅 알림만 쓸 거면 이것만 GitHub Actions secret으로 넣어도 됩니다.
- `DISCORD_TOKEN`, `DISCORD_GUILD_ID`, `AUTO_UPDATE_CHANNEL_ID`: 슬래시 커맨드 봇을 직접 띄울 때만 필요합니다.

웹훅 알림만 사용할 경우에는 `python main.py`로 봇 프로세스를 따로 띄울 필요가 없습니다.

## 실행
```bash
.\.venv\Scripts\python main.py
```

## DB 갱신
`/ctf` 계열 명령은 `CTF_DB_PATH`의 SQLite 스냅샷을 읽습니다. 로컬에서 직접 갱신하려면 아래 명령을 실행합니다.

```bash
.\.venv\Scripts\python -m ctf_bot.updater
```

기본 DB 경로는 `data/ctf_snapshot.db`입니다.

## GitHub Actions
- `.github/workflows/update-ctf-db.yml`가 UTC 기준 매 정시에 스냅샷을 갱신합니다.
- workflow는 이전 DB를 백업한 뒤 `python -m ctf_bot.updater`를 실행합니다.
- 그 다음 `python -m ctf_bot.notifier`가 이전/현재 DB를 비교해서 새로 유입된 `upcoming`/`ongoing` CTF만 Discord 웹훅으로 전송합니다.
- 알림 Embed에는 출처가 `CTFtime`인지 `K-CTF`인지 포함됩니다.
- 마지막으로 `data/ctf_snapshot.db`를 커밋/푸시합니다.
- 스냅샷 메타데이터가 매번 갱신되므로 workflow가 돌 때마다 커밋이 생성됩니다.
- 저장소를 처음 세팅해서 이전 DB가 없으면, 첫 실행은 부트스트랩으로 간주하고 알림을 보내지 않습니다.

GitHub 저장소 설정의 `Settings > Secrets and variables > Actions`에 `DISCORD_WEBHOOK_URL` secret을 추가하면 됩니다.

로컬에서 알림 diff만 시험하려면 아래처럼 dry run을 돌리면 됩니다.

```bash
.\.venv\Scripts\python -m ctf_bot.notifier --previous-db data/ctf_snapshot.previous.db --current-db data/ctf_snapshot.db --dry-run
```

## KCTF 참고
2026-03-30 기준 `http://k-ctf.org/`는 열리지만 `https://k-ctf.org/`는 응답하지 않았습니다. 그래서 기본값은 `http://k-ctf.org`로 잡았습니다.

또한 공개 JSON API는 제한적이어서, 대회 목록은 `K-CTF` 웹 페이지 HTML을 스크레이핑하고 아래 공개 엔드포인트를 함께 사용합니다.

- `GET /api/announcements/latest`
- `GET /api/contest-update-logs`

## 개발 메모
- `DISCORD_GUILD_ID`를 지정하면 슬래시 커맨드를 해당 길드에 빠르게 동기화합니다.
- 지정하지 않으면 글로벌 커맨드로 동기화합니다.
- `AUTO_UPDATE_CHANNEL_ID`를 지정하면 봇이 해당 채널의 자동 갱신 메시지를 1시간마다 수정합니다.
- DB 생성 시 `CTFtime` 제목과 겹치는 `K-CTF` 대회는 제외합니다.
- `ctf`/`kctf` 조회 커맨드의 `limit`은 상한이 없고, 비워두면 가능한 범위 내 전체 결과를 조회합니다.
