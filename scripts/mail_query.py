# test_all_accounts_mail_query.py
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

from infra.core.database import get_database_manager
from infra.core.logger import get_logger
from modules.mail_query import (
    MailQueryFilters,
    MailQueryOrchestrator,
    MailQueryRequest,
    PaginationOptions,
)

logger = get_logger(__name__)


class AllAccountsMailQueryTester:
    """모든 계정의 메일을 조회하는 테스터"""

    def __init__(self):
        self.mail_query = MailQueryOrchestrator()
        self.db = get_database_manager()

    async def get_all_active_accounts(self) -> List[Dict[str, Any]]:
        """활성화된 모든 계정 조회"""
        query = """
            SELECT 
                user_id, 
                user_name, 
                email,
                is_active,
                status,
                last_sync_time
            FROM accounts 
            WHERE is_active = 1
            ORDER BY user_id
        """

        accounts = self.db.fetch_all(query)
        return [dict(account) for account in accounts]

    async def query_account_mails(
        self, user_id: str, days_back: int = 60, max_mails: int = 10
    ) -> Dict[str, Any]:
        """특정 계정의 메일 조회"""

        start_time = datetime.now()

        try:
            # MailQueryRequest 생성
            request = MailQueryRequest(
                user_id=user_id,
                filters=MailQueryFilters(
                    date_from=datetime.now() - timedelta(days=days_back)
                ),
                pagination=PaginationOptions(top=max_mails, skip=0, max_pages=1),
                select_fields=[
                    "id",
                    "subject",
                    "from",
                    "sender",
                    "receivedDateTime",
                    "bodyPreview",
                    "hasAttachments",
                    "importance",
                    "isRead",
                ],
            )

            # 오케스트레이터 직접 호출
            async with self.mail_query as orchestrator:
                response = await orchestrator.mail_query_user_emails(request)

            # 결과 정리
            result = {
                "user_id": user_id,
                "success": True,
                "total_mails": response.total_fetched,
                "execution_time_ms": response.execution_time_ms,
                "has_more": response.has_more,
                "messages": [],
                "error": None,
            }

            # 메일 정보 추출 (상위 5개만)
            for mail in response.messages[:5]:
                sender = "Unknown"
                if mail.from_address and isinstance(mail.from_address, dict):
                    email_addr = mail.from_address.get("emailAddress", {})
                    sender = email_addr.get("address", "Unknown")

                result["messages"].append(
                    {
                        "id": mail.id,
                        "subject": (
                            mail.subject[:80] + "..."
                            if len(mail.subject) > 80
                            else mail.subject
                        ),
                        "sender": sender,
                        "received_date": mail.received_date_time.strftime(
                            "%Y-%m-%d %H:%M"
                        ),
                        "has_attachments": mail.has_attachments,
                        "is_read": mail.is_read,
                    }
                )

            return result

        except Exception as e:
            logger.error(f"계정 {user_id} 메일 조회 실패: {str(e)}")
            return {
                "user_id": user_id,
                "success": False,
                "total_mails": 0,
                "execution_time_ms": int(
                    (datetime.now() - start_time).total_seconds() * 1000
                ),
                "error": str(e),
            }

    async def test_all_accounts(
        self, days_back: int = 60, max_mails_per_account: int = 10
    ):
        """모든 계정 메일 조회 테스트"""

        print("🚀 모든 계정 메일 조회 테스트")
        print("=" * 80)
        print(f"설정: 최근 {days_back}일, 계정당 최대 {max_mails_per_account}개 메일")
        print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        # 1. 활성 계정 조회
        accounts = await self.get_all_active_accounts()
        print(f"\n📋 활성 계정 수: {len(accounts)}개")

        for account in accounts:
            print(f"  - {account['user_id']} ({account['user_name']})")

        # 2. 각 계정별 메일 조회
        print(f"\n📧 계정별 메일 조회 시작...")
        print("-" * 80)

        all_results = []
        total_mails = 0
        success_count = 0
        failed_accounts = []

        for i, account in enumerate(accounts, 1):
            user_id = account["user_id"]
            print(f"\n[{i}/{len(accounts)}] {user_id} 조회 중...")

            # 메일 조회
            result = await self.query_account_mails(
                user_id=user_id, days_back=days_back, max_mails=max_mails_per_account
            )

            all_results.append(result)

            if result["success"]:
                success_count += 1
                total_mails += result["total_mails"]

                print(
                    f"  ✅ 성공: {result['total_mails']}개 메일 ({result['execution_time_ms']}ms)"
                )

                # 메일 샘플 출력
                if result["messages"]:
                    print(f"  📋 최근 메일:")
                    for j, msg in enumerate(result["messages"][:3], 1):
                        print(f"    {j}. {msg['subject']}")
                        print(f"       발신자: {msg['sender']}")
                        print(f"       수신일: {msg['received_date']}")
            else:
                failed_accounts.append(user_id)
                print(f"  ❌ 실패: {result['error']}")

        # 3. 전체 결과 요약
        print("\n" + "=" * 80)
        print("📊 전체 결과 요약")
        print("=" * 80)

        print(f"\n✅ 성공: {success_count}/{len(accounts)} 계정")
        print(f"📧 총 메일 수: {total_mails}개")

        if failed_accounts:
            print(f"\n❌ 실패한 계정 ({len(failed_accounts)}개):")
            for account in failed_accounts:
                print(f"  - {account}")

        # 4. 계정별 통계
        print(f"\n📈 계정별 메일 통계:")
        print(f"{'계정 ID':<20} {'메일 수':>10} {'실행시간(ms)':>15} {'상태':>10}")
        print("-" * 60)

        for result in all_results:
            status = "성공" if result["success"] else "실패"
            print(
                f"{result['user_id']:<20} {result['total_mails']:>10} "
                f"{result['execution_time_ms']:>15} {status:>10}"
            )

        # 5. 실행 시간 분석
        total_execution_time = sum(r["execution_time_ms"] for r in all_results)
        avg_execution_time = (
            total_execution_time / len(all_results) if all_results else 0
        )

        print(f"\n⏱️  실행 시간 분석:")
        print(
            f"  - 총 실행 시간: {total_execution_time}ms ({total_execution_time/1000:.2f}초)"
        )
        print(f"  - 평균 실행 시간: {avg_execution_time:.0f}ms/계정")

        print(f"\n✅ 테스트 완료!")
        print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return {
            "total_accounts": len(accounts),
            "success_count": success_count,
            "failed_count": len(failed_accounts),
            "total_mails": total_mails,
            "results": all_results,
        }

    async def close(self):
        """리소스 정리"""
        await self.mail_query.close()


async def main():
    """메인 실행 함수"""
    tester = AllAccountsMailQueryTester()

    try:
        # 기본 설정으로 테스트
        await tester.test_all_accounts(
            days_back=60, max_mails_per_account=10  # 최근 60일  # 계정당 10개
        )

    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
