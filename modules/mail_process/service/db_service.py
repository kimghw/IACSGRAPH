"""데이터베이스 서비스 - 중복 확인 및 저장"""

import json
import hashlib
from datetime import datetime
from typing import Tuple, List, Optional
from infra.core.logger import get_logger
from infra.core.database import get_database_manager
from modules.mail_processor.mail_processor_schema import ProcessedMailData


class MailDatabaseService:
    """메일 데이터베이스 서비스"""

    def __init__(self):
        self.logger = get_logger(__name__)
        self.db_manager = get_database_manager()

    def check_duplicate_by_content_hash(self, mail_id: str, content: str) -> Tuple[bool, List[str]]:
        """
        내용 해시 기반 중복 확인
        
        Args:
            mail_id: 메일 ID
            content: 정제된 메일 내용
            
        Returns:
            (중복 여부, 기존 키워드 리스트)
        """
        # 내용 해시 생성
        content_hash = self._generate_content_hash(content)
        
        # 해시 기반 중복 검사
        query = """
            SELECT keywords 
            FROM mail_history 
            WHERE content_hash = ? OR message_id = ?
            LIMIT 1
        """
        
        result = self.db_manager.fetch_one(query, (content_hash, mail_id))
        
        if result:
            # 기존 키워드 파싱
            try:
                existing_keywords = json.loads(result['keywords']) if result['keywords'] else []
            except (json.JSONDecodeError, TypeError):
                existing_keywords = []
            
            self.logger.debug(f"중복 메일 발견 - ID: {mail_id}, 기존 키워드: {existing_keywords}")
            return True, existing_keywords
        
        return False, []

    def save_mail_with_hash(self, processed_mail: ProcessedMailData, clean_content: str) -> None:
        """
        메일 히스토리 저장 (해시 포함)
        
        Args:
            processed_mail: 처리된 메일 데이터
            clean_content: 정제된 메일 내용
        """
        # 내용 해시 생성
        content_hash = self._generate_content_hash(clean_content)
        
        # 실제 account_id 조회
        actual_account_id = self._get_actual_account_id(processed_mail.account_id)
        
        # content_hash 컬럼 확인 및 추가
        self._ensure_content_hash_column()
        
        # 메일 히스토리 저장
        query = """
            INSERT INTO mail_history (
                account_id, message_id, received_time, subject, 
                sender, keywords, processed_at, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        keywords_json = json.dumps(processed_mail.keywords, ensure_ascii=False)
        
        self.db_manager.execute_query(query, (
            actual_account_id,
            processed_mail.mail_id,
            processed_mail.sent_time,
            processed_mail.subject,
            processed_mail.sender_address,
            keywords_json,
            processed_mail.processed_at,
            content_hash
        ))
        
        self.logger.info(f"메일 저장 완료 - ID: {processed_mail.mail_id}, 해시: {content_hash[:8]}...")

    def get_active_accounts(self) -> List[dict]:
        """
        활성 계정 목록 조회
        
        Returns:
            활성 계정 리스트
        """
        query = """
            SELECT id, user_id, user_name, last_sync_time, access_token, refresh_token
            FROM accounts 
            WHERE is_active = 1 
            ORDER BY last_sync_time ASC NULLS FIRST
        """
        
        rows = self.db_manager.fetch_all(query)
        accounts = []
        
        for row in rows:
            account = dict(row)
            # datetime 변환
            if account['last_sync_time']:
                account['last_sync_time'] = datetime.fromisoformat(account['last_sync_time'])
            accounts.append(account)
        
        self.logger.info(f"활성 계정 {len(accounts)}개 조회됨")
        return accounts

    def update_account_sync_time(self, account_id: str, sync_time: datetime) -> None:
        """
        계정 동기화 시간 업데이트
        
        Args:
            account_id: 계정 ID
            sync_time: 동기화 시간
        """
        query = "UPDATE accounts SET last_sync_time = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?"
        self.db_manager.execute_query(query, (sync_time, account_id))
        self.logger.debug(f"계정 {account_id} 동기화 시간 업데이트: {sync_time}")

    def record_account_error(self, account_id: str, error_message: str) -> None:
        """
        계정 에러 기록
        
        Args:
            account_id: 계정 ID
            error_message: 에러 메시지
        """
        import uuid
        
        log_query = """
            INSERT INTO processing_logs (run_id, account_id, log_level, message)
            VALUES (?, (SELECT id FROM accounts WHERE user_id = ?), 'ERROR', ?)
        """
        
        run_id = str(uuid.uuid4())
        self.db_manager.execute_query(log_query, (run_id, account_id, error_message))
        self.logger.error(f"계정 {account_id} 에러 기록: {error_message}")

    def _generate_content_hash(self, content: str) -> str:
        """내용 해시 생성"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _get_actual_account_id(self, account_id: str) -> int:
        """문자열 account_id를 실제 DB ID로 변환"""
        if isinstance(account_id, int):
            return account_id
            
        account_query = "SELECT id FROM accounts WHERE user_id = ?"
        account_result = self.db_manager.fetch_one(account_query, (account_id,))
        
        if account_result:
            return account_result['id']
        else:
            # 테스트용 계정이 없는 경우 임시로 생성
            self.logger.warning(f"계정 {account_id}가 존재하지 않음, 임시 계정 생성")
            insert_account_query = """
                INSERT INTO accounts (user_id, user_name, is_active) 
                VALUES (?, ?, 1)
            """
            self.db_manager.execute_query(insert_account_query, (
                account_id, 
                f"Test User ({account_id})"
            ))
            
            # 생성된 계정 ID 조회
            account_result = self.db_manager.fetch_one(account_query, (account_id,))
            return account_result['id']

    def _ensure_content_hash_column(self) -> None:
        """content_hash 컬럼 존재 확인 및 추가"""
        try:
            alter_query = "ALTER TABLE mail_history ADD COLUMN content_hash TEXT"
            self.db_manager.execute_query(alter_query)
            self.logger.info("mail_history 테이블에 content_hash 컬럼 추가됨")
        except Exception:
            # 이미 컬럼이 있거나 다른 이유로 실패한 경우 무시
            pass