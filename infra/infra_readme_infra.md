# Infra 모듈

## 1. 개요

IACSGraph 프로젝트의 모든 모듈이 공유하는 핵심 기반 서비스를 제공합니다. 설정 관리, 데이터베이스 연결, 로깅, 인증 클라이언트 등 공통 기능을 중앙에서 관리하여 모듈 간의 일관성을 유지하고 중복을 제거합니다.

## 2. 핵심 컴포넌트 (`infra/core`)

각 컴포넌트는 싱글턴 팩토리 함수(`get_...()`)를 통해 접근하여 애플리케이션 전체에서 동일한 인스턴스를 공유합니다.

- **`config.py`**: `.env` 파일에서 환경 변수를 로드하고 전역 설정을 제공합니다.
- **`database.py`**: SQLite 데이터베이스 연결을 관리하고, CRUD 및 트랜잭션을 위한 메서드를 제공합니다. 애플리케이션 시작 시 `infra/migrations/`의 스키마를 기반으로 DB를 초기화합니다.
- **`token_service.py`**: `accounts` 테이블과 연동하여 OAuth 토큰(Access/Refresh)을 저장, 조회, 자동 갱신하는 로직을 담당합니다.
- **`oauth_client.py`**: Microsoft Graph API와의 OAuth 2.0 통신을 담당하며, 인증 코드 교환 및 토큰 갱신 요청을 처리합니다.
- **`logger.py`**: 구조화된 로그(JSON 형식)를 생성하고 관리합니다.
- **`exceptions.py`**: `IACSGraphError`를 기반으로 하는 표준 예외 클래스를 정의하여 일관된 오류 처리를 지원합니다.
- **`kafka_client.py`**: Kafka 연동을 위한 Producer/Consumer 기능을 제공합니다. (이벤트 기반 아키텍처용)

### 2.1 토큰 서비스 (`token_service.py`) 상세

토큰 서비스는 OAuth 토큰의 전체 생명주기를 관리하는 핵심 컴포넌트입니다.

#### 주요 기능

1. **토큰 저장 및 관리**
   - `store_tokens()`: 새로운 토큰 정보를 데이터베이스에 저장
   - `revoke_tokens()`: 토큰 무효화
   - `cleanup_expired_tokens()`: 만료된 토큰 정리

2. **토큰 조회 및 자동 갱신**
   - `get_valid_access_token()`: 유효한 액세스 토큰 반환 (만료 시 자동 갱신)
   - `validate_and_refresh_token()`: 토큰 유효성 검증 및 필요 시 갱신
   - `force_token_refresh()`: 강제 토큰 갱신

3. **인증 상태 관리**
   - `check_authentication_status()`: 계정의 인증 상태 확인
   - `update_account_status()`: 계정 상태 업데이트 (ACTIVE, INACTIVE, REAUTH_REQUIRED 등)
   - `deactivate_account()`: 계정 비활성화

4. **계정 정보 조회**
   - `get_account_info()`: 특정 계정 정보 조회
   - `get_all_active_accounts()`: 모든 활성 계정 조회
   - `get_accounts_by_status()`: 상태별 계정 조회
   - `get_accounts_requiring_reauth()`: 재인증 필요 계정 조회

#### 토큰 갱신 흐름

```mermaid
graph TD
    A[토큰 요청] --> B{토큰 유효?}
    B -->|예| C[액세스 토큰 반환]
    B -->|아니오| D{리프레시 토큰 존재?}
    D -->|예| E[토큰 갱신 시도]
    D -->|아니오| F[재인증 필요]
    E --> G{갱신 성공?}
    G -->|예| H[새 토큰 저장]
    G -->|아니오| F
    H --> C
```

## 3. 데이터베이스 스키마 (`infra/migrations/`)

`database.py`가 시작될 때 `infra/migrations/` 폴더의 `.sql` 파일들이 실행되어 데이터베이스 스키마를 구성합니다. 최종 테이블 구조는 다음과 같습니다.

### `accounts`
사용자 계정 정보를 관리하는 핵심 테이블입니다.

```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL UNIQUE,
    user_name TEXT NOT NULL,
    email TEXT,
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    enrollment_file_path TEXT,
    enrollment_file_hash TEXT,
    oauth_client_id TEXT,
    oauth_client_secret TEXT, -- 암호화된 데이터
    oauth_tenant_id TEXT,
    oauth_redirect_uri TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    auth_type TEXT,
    delegated_permissions TEXT -- JSON 형태
);
```

### `mail_history`
처리된 메일의 이력을 저장하여 중복 처리를 방지합니다.

```sql
CREATE TABLE mail_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    message_id TEXT NOT NULL UNIQUE,
    received_time TIMESTAMP NOT NULL,
    subject TEXT,
    sender TEXT,
    keywords TEXT, -- JSON 형태의 텍스트
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts (id)
);
```

### `processing_logs`
특정 작업 실행(`run_id`)에 대한 상세 로그를 기록합니다.

```sql
CREATE TABLE processing_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    account_id INTEGER,
    log_level TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts (id)
);
```

### `account_audit_logs`
`accounts` 테이블의 주요 변경 사항에 대한 감사 추적 로그를 남깁니다.

```sql
CREATE TABLE account_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER,
    action TEXT NOT NULL,
    old_values TEXT, -- JSON 형태
    new_values TEXT, -- JSON 형태
    changed_by TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts (id)
);
```

## 4. 사용법

다른 모듈에서는 필요한 `infra` 서비스를 `import`하여 사용합니다.

### 4.1 기본 사용법

```python
# 필요한 인프라 서비스들을 import
from infra.core import get_config, get_database_manager, get_logger
from infra.core.exceptions import DatabaseError

# 설정 객체 가져오기
config = get_config()
logger = get_logger(__name__)

logger.info(f"DB 경로: {config.database_path}")

# 데이터베이스 매니저를 통한 쿼리 실행
db_manager = get_database_manager()
try:
    # 트랜잭션 사용 예시
    with db_manager.transaction() as conn:
        # 이 블록 내의 모든 DB 작업은 원자적으로 처리됩니다.
        user_id = "user@example.com"
        account = db_manager.fetch_one("SELECT * FROM accounts WHERE user_id = ?", (user_id,))
        if account:
            logger.info(f"{user_id} 계정을 찾았습니다.")

except DatabaseError as e:
    logger.error(f"데이터베이스 작업 실패: {e}", exc_info=True)
```

### 4.2 토큰 서비스 사용법

```python
from infra.core import get_token_service, get_logger
from infra.core.exceptions import TokenError, TokenExpiredError

# 토큰 서비스 인스턴스 가져오기
token_service = get_token_service()
logger = get_logger(__name__)

# 1. 유효한 액세스 토큰 가져오기 (자동 갱신 포함)
async def get_access_token_example(user_id: str):
    try:
        access_token = await token_service.get_valid_access_token(user_id)
        if access_token:
            logger.info(f"유효한 토큰을 획득했습니다: {user_id}")
            return access_token
        else:
            logger.warning(f"토큰을 가져올 수 없습니다: {user_id}")
            return None
    except TokenExpiredError:
        logger.error(f"리프레시 토큰이 만료되었습니다: {user_id}")
        # 재인증 필요
        return None

# 2. 토큰 유효성 검증 및 갱신
async def validate_token_example(user_id: str):
    result = await token_service.validate_and_refresh_token(user_id)
    
    if result['status'] == 'valid':
        logger.info("토큰이 유효합니다")
        return result['access_token']
    elif result['status'] == 'refreshed':
        logger.info("토큰이 갱신되었습니다")
        return result['access_token']
    else:
        logger.warning(f"토큰 검증 실패: {result['message']}")
        return None

# 3. 인증 상태 확인
async def check_auth_status_example(user_id: str):
    auth_status = await token_service.check_authentication_status(user_id)
    
    logger.info(f"인증 상태: {auth_status['status']}")
    logger.info(f"재인증 필요: {auth_status['requires_reauth']}")
    
    if auth_status['requires_reauth']:
        # 재인증 프로세스 시작
        logger.warning(f"재인증이 필요합니다: {auth_status['message']}")
    
    return auth_status

# 4. 새로운 토큰 저장
async def store_new_tokens_example(user_id: str, token_info: dict):
    try:
        account_id = await token_service.store_tokens(
            user_id=user_id,
            token_info=token_info,
            user_name="사용자 이름"
        )
        logger.info(f"토큰 저장 완료: account_id={account_id}")
        return account_id
    except Exception as e:
        logger.error(f"토큰 저장 실패: {str(e)}")
        return None

# 5. 계정별 상태 조회
async def get_accounts_by_status_example():
    # 재인증이 필요한 계정들 조회
    reauth_accounts = await token_service.get_accounts_requiring_reauth()
    for account in reauth_accounts:
        logger.info(f"재인증 필요: {account['user_id']}")
    
    # 비활성 계정들 조회
    inactive_accounts = await token_service.get_inactive_accounts()
    for account in inactive_accounts:
        logger.info(f"비활성 계정: {account['user_id']}")
```

### 4.3 통합 사용 예시

```python
import asyncio
from infra.core import get_token_service, get_oauth_client, get_logger

async def process_user_request(user_id: str):
    """사용자 요청 처리 시 토큰 관리 예시"""
    token_service = get_token_service()
    oauth_client = get_oauth_client()
    logger = get_logger(__name__)
    
    try:
        # 1. 유효한 액세스 토큰 가져오기
        access_token = await token_service.get_valid_access_token(user_id)
        
        if not access_token:
            logger.error(f"유효한 토큰이 없습니다: {user_id}")
            return None
        
        # 2. 토큰을 사용하여 API 호출
        # 예: Microsoft Graph API 호출
        user_info = await oauth_client.get_user_info(access_token)
        
        # 3. 마지막 동기화 시간 업데이트
        await token_service.update_last_sync_time(user_id)
        
        return user_info
        
    except TokenExpiredError:
        # 토큰이 만료되어 갱신할 수 없는 경우
        logger.warning(f"토큰 갱신 실패, 재인증 필요: {user_id}")
        await token_service.update_account_status(user_id, "REAUTH_REQUIRED")
        return None
        
    except Exception as e:
        logger.error(f"요청 처리 실패: {user_id}, error={str(e)}")
        return None

# 실행 예시
if __name__ == "__main__":
    user_id = "user@example.com"
    result = asyncio.run(process_user_request(user_id))
```

## 5. 필수 환경 설정 (`.env` 파일)

프로젝트 루트에 아래와 같은 `.env` 파일을 생성해야 합니다.

```env
# 데이터베이스 파일 경로
DATABASE_PATH=./data/iacsgraph.db

# 데이터 암호화를 위한 32바이트 URL-safe base64 키
# (생성 예: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
ENCRYPTION_KEY=your_secret_encryption_key_here

# 계정 설정 파일(enrollment/*.yaml)이 위치한 디렉터리
ENROLLMENT_DIRECTORY=./enrollment

# 전역 로그 레벨 (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO
```

## 6. 아키텍처 원칙

- **단방향 의존성**: 모든 상위 모듈(`account`, `auth` 등)은 `infra` 모듈에 의존할 수 있지만, `infra` 모듈은 다른 상위 모듈을 절대 참조하지 않습니다.
- **싱글톤 패턴**: `get_...()` 팩토리 함수를 통해 모든 서비스가 싱글턴으로 관리되어 애플리케이션 전체에서 동일한 인스턴스를 공유합니다.
